import fs from "node:fs";
import path from "node:path";
import { captureProcessIdentity, terminateValidatedJobWorker } from "./process.mjs";
import { jobsDirForCwd, stateDirForCwd } from "./state.mjs";

const JOB_ID_PATTERN = /^[A-Za-z0-9._-]+$/;
const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled", "cancel_failed"]);

function ensureJobsDir(cwd = process.cwd(), env = process.env) {
  const dir = jobsDirForCwd(cwd, env);
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  return dir;
}

function jobFile(cwd, jobId, env = process.env) {
  if (!JOB_ID_PATTERN.test(jobId)) {
    throw new Error(`Invalid job id "${jobId}".`);
  }
  return path.join(ensureJobsDir(cwd, env), `${jobId}.json`);
}

function writeJob(cwd, job, env = process.env) {
  const file = jobFile(cwd, job.id, env);
  const tmpFile = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmpFile, `${JSON.stringify(job, null, 2)}\n`, "utf8");
  fs.renameSync(tmpFile, file);
  return job;
}

export function createJob(cwd, job, env = process.env) {
  const id = job.id ?? `job-${Date.now().toString(36)}-${Math.random().toString(16).slice(2, 8)}`;
  const now = new Date().toISOString();
  const payload = {
    id,
    status: "queued",
    createdAt: now,
    updatedAt: now,
    ...job,
    id
  };
  return writeJob(cwd, payload, env);
}

export function reserveJob(cwd, job, workerCommand, env = process.env) {
  return createJob(cwd, {
    ...job,
    reservationMode: "host-forwarded",
    reservedBy: "claude-host",
    workerCommand
  }, env);
}

function isValidReservedWorkerCommand(job, jobId) {
  if (job.reservationMode !== "host-forwarded") {
    return false;
  }
  if (!Array.isArray(job.workerCommand)) {
    return false;
  }
  const commandIndex = job.workerCommand.indexOf("run-reserved-job");
  if (commandIndex < 0) {
    return false;
  }
  if (!String(job.workerCommand[commandIndex - 1] ?? "").endsWith("claude-companion.mjs")) {
    return false;
  }
  const jobIdFlagIndex = job.workerCommand.indexOf("--job-id", commandIndex + 1);
  return jobIdFlagIndex >= 0 && job.workerCommand[jobIdFlagIndex + 1] === jobId;
}

export function claimReservedJob(cwd, jobId, workerPid = process.pid, env = process.env) {
  const file = jobFile(cwd, jobId, env);
  if (!fs.existsSync(file)) {
    return { status: "not_found", jobId };
  }
  const original = fs.readFileSync(file, "utf8");
  let job;
  try {
    job = JSON.parse(original);
  } catch (error) {
    return {
      status: "not_claimed",
      jobId,
      reason: `Reserved job state is corrupt: ${error.message || String(error)}`
    };
  }
  if (job.status !== "queued") {
    return { status: "not_claimed", jobId, job };
  }
  if (!isValidReservedWorkerCommand(job, jobId)) {
    return {
      status: "not_claimed",
      jobId,
      reason: "Job is not a valid host-forwarded reservation.",
      job
    };
  }
  const running = {
    ...job,
    status: "running",
    workerPid,
    pidIdentity: captureProcessIdentity(workerPid),
    startedAt: new Date().toISOString(),
    updatedAt: new Date().toISOString()
  };
  // Acquire an exclusive claim lock so two racing workers cannot both pass the
  // read-compare-rename window. mkdir is atomic; EEXIST means another worker is
  // mid-claim, so we lose the race. The claim window is sub-second, so a lock
  // older than CLAIM_LOCK_STALE_MS is an orphan (the holder was hard-killed mid
  // claim) and is reclaimed once to avoid permanently wedging the job.
  const lockDir = `${file}.claim.lock`;
  const ownerFile = `${lockDir}/owner`;
  // Unique per-claim token so cleanup never deletes a lock a *different* claim
  // now owns (the prior bug: a paused holder reclaimed as stale, then its own
  // finally removed the new owner's lock and allowed a double claim).
  const ownerToken = `${process.pid}.${process.hrtime.bigint().toString(36)}`;
  const CLAIM_LOCK_STALE_MS = 30 * 1000;
  const acquireLock = () => {
    try {
      fs.mkdirSync(lockDir);
      // Stamp ownership immediately so cleanup can verify we still hold it.
      fs.writeFileSync(ownerFile, ownerToken, "utf8");
      return { ok: true };
    } catch (error) {
      if (error && error.code === "EEXIST") {
        return { ok: false };
      }
      throw error;
    }
  };
  // Only the holder we observed-as-stale may be reclaimed: re-stat after the
  // remove to ensure we did not delete a lock that was refreshed in between.
  let locked = acquireLock();
  if (!locked.ok) {
    let staleMtime = null;
    try {
      staleMtime = fs.statSync(lockDir).mtimeMs;
    } catch {
      // Lock vanished between mkdir and stat; treat as reclaimable and retry.
      staleMtime = 0;
    }
    if (staleMtime === 0 || Date.now() - staleMtime > CLAIM_LOCK_STALE_MS) {
      try {
        // Re-verify the lock has not been refreshed since we judged it stale,
        // then remove exactly that orphan.
        let current = null;
        try {
          current = fs.statSync(lockDir).mtimeMs;
        } catch {
          current = 0;
        }
        if (current === 0 || current === staleMtime) {
          fs.rmSync(lockDir, { recursive: true, force: true });
        }
      } catch {
        // Another worker may have just reclaimed it; fall through to the retry.
      }
      locked = acquireLock();
    }
  }
  if (!locked.ok) {
    return {
      status: "not_claimed",
      jobId,
      reason: "Job is being claimed by another worker."
    };
  }
  const tmpFile = `${file}.${process.pid}.claim.tmp`;
  try {
    // Re-read under the lock: another worker may have already claimed and
    // changed the queued state before we acquired the lock.
    if (fs.readFileSync(file, "utf8") !== original) {
      return {
        status: "not_claimed",
        jobId,
        reason: "Job changed before it could be claimed."
      };
    }
    fs.writeFileSync(tmpFile, `${JSON.stringify(running, null, 2)}\n`, "utf8");
    fs.renameSync(tmpFile, file);
    return { status: "claimed", job: running };
  } finally {
    fs.rmSync(tmpFile, { force: true });
    // Only remove the lock if we still own it; never delete a lock another
    // claim re-acquired (which would let two workers run the same job).
    try {
      if (fs.readFileSync(ownerFile, "utf8") === ownerToken) {
        fs.rmSync(lockDir, { recursive: true, force: true });
      }
    } catch {
      // Owner file missing/unreadable: the lock was already reclaimed by
      // another worker; leave it alone.
    }
  }
}

export function updateJob(cwd, jobId, updates, env = process.env) {
  const job = readJob(cwd, jobId, env);
  if (!job) {
    return null;
  }
  const updated = {
    ...job,
    ...updates,
    updatedAt: new Date().toISOString()
  };
  return writeJob(cwd, updated, env);
}

export function updateJobUnlessTerminal(cwd, jobId, updates, env = process.env) {
  const job = readJob(cwd, jobId, env);
  if (!job) {
    return null;
  }
  if (TERMINAL_STATUSES.has(job.status)) {
    return job;
  }
  const updated = {
    ...job,
    ...updates,
    updatedAt: new Date().toISOString()
  };
  return writeJob(cwd, updated, env);
}

export function markJobRunning(cwd, jobId, workerPid, env = process.env) {
  return updateJob(cwd, jobId, {
    status: "running",
    workerPid,
    pidIdentity: captureProcessIdentity(workerPid),
    startedAt: new Date().toISOString()
  }, env);
}

export function finishJob(cwd, jobId, result, env = process.env) {
  const current = readJob(cwd, jobId, env);
  if (current && TERMINAL_STATUSES.has(current.status)) {
    return current;
  }
  return updateJob(cwd, jobId, {
    status: result.status === 0 ? "succeeded" : "failed",
    exitStatus: result.status,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    error: result.error ?? "",
    finishedAt: new Date().toISOString()
  }, env);
}

export function listJobs(cwd = process.cwd(), env = process.env) {
  const dir = ensureJobsDir(cwd, env);
  const jobs = fs.readdirSync(dir)
    .filter((name) => name.endsWith(".json"))
    .map((name) => {
      try {
        return JSON.parse(fs.readFileSync(path.join(dir, name), "utf8"));
      } catch {
        return {
          id: name.slice(0, -".json".length),
          status: "corrupt"
        };
      }
    })
    .sort((left, right) => String(right.createdAt ?? "").localeCompare(String(left.createdAt ?? "")));
  return {
    stateDir: stateDirForCwd(cwd, env),
    jobs
  };
}

export function readJob(cwd, jobId, env = process.env) {
  const file = jobFile(cwd, jobId, env);
  if (!fs.existsSync(file)) {
    return null;
  }
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    return {
      id: jobId,
      status: "corrupt",
      stateError: error.message || String(error)
    };
  }
}

export function resultForJob(cwd, jobId, env = process.env) {
  const job = readJob(cwd, jobId, env);
  if (!job) {
    return { status: "not_found", jobId };
  }
  if (job.status === "corrupt") {
    return { status: "corrupt", jobId, job };
  }
  const updated = {
    ...job,
    resultViewedAt: new Date().toISOString()
  };
  writeJob(cwd, updated, env);
  return { status: "ok", job: updated };
}

export function cancelJob(cwd, jobId, env = process.env) {
  const job = readJob(cwd, jobId, env);
  if (!job) {
    return { status: "not_found", jobId };
  }
  if (job.status === "queued") {
    const updated = {
      ...job,
      status: "cancelled",
      cancelledAt: new Date().toISOString()
    };
    writeJob(cwd, updated, env);
    return { status: "cancelled", jobId, job: updated };
  }
  if (job.status === "running" && Number.isInteger(job.workerPid)) {
    const termination = terminateValidatedJobWorker(job.workerPid, jobId);
    if (termination.ok) {
      const updated = updateJobUnlessTerminal(cwd, jobId, {
        status: "cancelled",
        cancelledAt: new Date().toISOString(),
        cancelIdentity: termination.identity
      }, env);
      return { status: "cancelled", jobId, job: updated };
    }
    const updated = updateJobUnlessTerminal(cwd, jobId, {
      status: "cancel_failed",
      cancelFailedAt: new Date().toISOString(),
      cancelFailureReason: `Running job cancellation requires process identity validation; refusing to signal PID: ${termination.reason}`
    }, env);
    return {
      status: "cancel_failed",
      jobId,
      reason: `Running job cancellation requires process identity validation; refusing to signal PID: ${termination.reason}`,
      job: updated
    };
  }
  if (job.status === "running") {
    const updated = updateJobUnlessTerminal(cwd, jobId, {
      status: "cancel_failed",
      cancelFailedAt: new Date().toISOString(),
      cancelFailureReason: "Running job has no valid workerPid."
    }, env);
    return {
      status: "cancel_failed",
      jobId,
      reason: "Running job has no valid workerPid.",
      job: updated
    };
  }
  if (TERMINAL_STATUSES.has(job.status)) {
    return { status: job.status, jobId, job };
  }
  return {
    status: "cancel_failed",
    jobId,
    reason: "No validated running process is recorded for this job."
  };
}
