import fs from "node:fs";
import process from "node:process";

import { JOB_HEARTBEAT_INTERVAL_MS } from "./job-lifecycle.mjs";
import { mutateJobFile, readJobFile, resolveJobFile, resolveJobLogFile, updateState, upsertJob, writeJobFile } from "./state.mjs";

export const SESSION_ID_ENV = "CODEX_COMPANION_SESSION_ID";

export function nowIso() {
  return new Date().toISOString();
}

function normalizeProgressEvent(value) {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return {
      message: String(value.message ?? "").trim(),
      phase: typeof value.phase === "string" && value.phase.trim() ? value.phase.trim() : null,
      threadId: typeof value.threadId === "string" && value.threadId.trim() ? value.threadId.trim() : null,
      turnId: typeof value.turnId === "string" && value.turnId.trim() ? value.turnId.trim() : null,
      stderrMessage: value.stderrMessage == null ? null : String(value.stderrMessage).trim(),
      logTitle: typeof value.logTitle === "string" && value.logTitle.trim() ? value.logTitle.trim() : null,
      logBody: value.logBody == null ? null : String(value.logBody).trimEnd()
    };
  }

  return {
    message: String(value ?? "").trim(),
    phase: null,
    threadId: null,
    turnId: null,
    stderrMessage: String(value ?? "").trim(),
    logTitle: null,
    logBody: null
  };
}

export function appendLogLine(logFile, message) {
  const normalized = String(message ?? "").trim();
  if (!logFile || !normalized) {
    return;
  }
  fs.appendFileSync(logFile, `[${nowIso()}] ${normalized}\n`, "utf8");
}

export function appendLogBlock(logFile, title, body) {
  if (!logFile || !body) {
    return;
  }
  fs.appendFileSync(logFile, `\n[${nowIso()}] ${title}\n${String(body).trimEnd()}\n`, "utf8");
}

export function createJobLogFile(workspaceRoot, jobId, title) {
  const logFile = resolveJobLogFile(workspaceRoot, jobId);
  fs.writeFileSync(logFile, "", "utf8");
  if (title) {
    appendLogLine(logFile, `Starting ${title}.`);
  }
  return logFile;
}

export function createJobRecord(base, options = {}) {
  const env = options.env ?? process.env;
  const sessionId = env[options.sessionIdEnv ?? SESSION_ID_ENV];
  return {
    ...base,
    createdAt: nowIso(),
    ...(sessionId ? { sessionId } : {})
  };
}

function sharedProgressJobPatch(job) {
  const {
    request,
    result,
    rendered,
    backgroundLease,
    backgroundLeaseId,
    lease,
    ...shared
  } = job;
  return shared;
}

function removeOrphanProgressPatch(workspaceRoot, jobId) {
  updateState(workspaceRoot, (state) => {
    const existing = state.jobs.find((job) => job.id === jobId);
    if (!existing) {
      return;
    }
    const hasLifecycleFields = existing.status
      || existing.kind
      || existing.title
      || existing.workspaceRoot
      || existing.logFile
      || existing.pid
      || existing.sessionId;
    if (!hasLifecycleFields) {
      state.jobs = state.jobs.filter((job) => job.id !== jobId);
    }
  });
}

export function createJobProgressUpdater(workspaceRoot, jobId) {
  let lastPhase = null;
  let lastThreadId = null;
  let lastTurnId = null;

  return (event) => {
    if (process.env.CODEX_FOR_CLAUDE_DISABLE_PROGRESS_UPDATES === "1") {
      return;
    }

    const normalized = normalizeProgressEvent(event);
    const patch = { id: jobId };
    let changed = false;

    if (normalized.phase && normalized.phase !== lastPhase) {
      lastPhase = normalized.phase;
      patch.phase = normalized.phase;
      changed = true;
    }

    if (normalized.threadId && normalized.threadId !== lastThreadId) {
      lastThreadId = normalized.threadId;
      patch.threadId = normalized.threadId;
      changed = true;
    }

    if (normalized.turnId && normalized.turnId !== lastTurnId) {
      lastTurnId = normalized.turnId;
      patch.turnId = normalized.turnId;
      changed = true;
    }

    if (!changed) {
      return;
    }

    upsertJob(workspaceRoot, patch);
    const updated = mutateJobFile(workspaceRoot, jobId, (storedJob) => {
      if (!storedJob?.id) {
        return null;
      }
      return {
        ...storedJob,
        ...patch
      };
    });
    if (!updated) {
      removeOrphanProgressPatch(workspaceRoot, jobId);
      return;
    }
    upsertJob(workspaceRoot, sharedProgressJobPatch(updated));
  };
}

export function createProgressReporter({ stderr = false, logFile = null, onEvent = null } = {}) {
  if (!stderr && !logFile && !onEvent) {
    return null;
  }

  return (eventOrMessage) => {
    const event = normalizeProgressEvent(eventOrMessage);
    const stderrMessage = event.stderrMessage ?? event.message;
    if (stderr && stderrMessage) {
      process.stderr.write(`[codex] ${stderrMessage}\n`);
    }
    appendLogLine(logFile, event.message);
    appendLogBlock(logFile, event.logTitle, event.logBody);
    onEvent?.(event);
  };
}

function readStoredJobOrNull(workspaceRoot, jobId) {
  const jobFile = resolveJobFile(workspaceRoot, jobId);
  if (!fs.existsSync(jobFile)) {
    return null;
  }
  return readJobFile(jobFile);
}

export function writeHeartbeatIfRunning(job, nowMs = null, isRunning = null) {
  if (process.env.CODEX_FOR_CLAUDE_DISABLE_HEARTBEAT === "1") {
    return false;
  }
  if (!job?.workspaceRoot || !job?.id) {
    return false;
  }
  if (job.status !== "queued" && job.status !== "running") {
    return false;
  }
  const shouldWrite = isRunning ?? (() => true);
  if (!shouldWrite()) {
    return false;
  }

  const heartbeatAtMs = Number.isFinite(nowMs) ? nowMs : Date.now();
  const updated = mutateJobFile(job.workspaceRoot, job.id, (storedJob) => {
    if (!storedJob?.id || !storedJob.status || ["completed", "failed", "cancelled"].includes(storedJob.status)) {
      return null;
    }
    return {
      ...storedJob,
      heartbeatAtMs,
      heartbeatAt: new Date(heartbeatAtMs).toISOString()
    };
  });
  return Boolean(updated);
}

export async function runTrackedJob(job, runner, options = {}) {
  const runningRecord = {
    ...job,
    status: "running",
    startedAt: nowIso(),
    phase: "starting",
    pid: process.pid,
    logFile: options.logFile ?? job.logFile ?? null
  };
  upsertJob(job.workspaceRoot, runningRecord);
  writeJobFile(job.workspaceRoot, job.id, runningRecord);
  writeHeartbeatIfRunning(runningRecord);
  let heartbeatActive = true;
  let heartbeat = null;
  if (process.env.CODEX_FOR_CLAUDE_DISABLE_HEARTBEAT !== "1") {
    heartbeat = setInterval(() => {
      if (heartbeatActive) {
        writeHeartbeatIfRunning(runningRecord);
      }
    }, JOB_HEARTBEAT_INTERVAL_MS);
  }
  heartbeat?.unref?.();

  try {
    const execution = await runner();
    const completionStatus = execution.exitStatus === 0 ? "completed" : "failed";
    const completedAt = nowIso();
    heartbeatActive = false;
    if (heartbeat) {
      clearInterval(heartbeat);
      heartbeat = null;
    }
    upsertJob(job.workspaceRoot, {
      id: job.id,
      status: completionStatus,
      threadId: execution.threadId ?? null,
      turnId: execution.turnId ?? null,
      summary: execution.summary,
      phase: completionStatus === "completed" ? "done" : "failed",
      pid: null,
      completedAt
    });
    writeJobFile(job.workspaceRoot, job.id, {
      ...runningRecord,
      status: completionStatus,
      threadId: execution.threadId ?? null,
      turnId: execution.turnId ?? null,
      pid: null,
      phase: completionStatus === "completed" ? "done" : "failed",
      completedAt,
      result: execution.payload,
      rendered: execution.rendered
    });
    appendLogBlock(options.logFile ?? job.logFile ?? null, "Final output", execution.rendered);
    return execution;
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    heartbeatActive = false;
    if (heartbeat) {
      clearInterval(heartbeat);
      heartbeat = null;
    }
    const existing = readStoredJobOrNull(job.workspaceRoot, job.id) ?? runningRecord;
    const completedAt = nowIso();
    upsertJob(job.workspaceRoot, {
      id: job.id,
      status: "failed",
      phase: "failed",
      pid: null,
      errorMessage,
      completedAt
    });
    writeJobFile(job.workspaceRoot, job.id, {
      ...existing,
      status: "failed",
      phase: "failed",
      errorMessage,
      pid: null,
      completedAt,
      logFile: options.logFile ?? job.logFile ?? existing.logFile ?? null
    });
    throw error;
  } finally {
    heartbeatActive = false;
    if (heartbeat) {
      clearInterval(heartbeat);
    }
  }
}
