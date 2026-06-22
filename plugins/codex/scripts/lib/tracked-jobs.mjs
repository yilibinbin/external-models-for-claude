import fs from "node:fs";
import process from "node:process";

import { JOB_HEARTBEAT_INTERVAL_MS } from "./job-lifecycle.mjs";
import {
  hasEndedSession,
  loadState,
  mutateJobFile,
  readJobFile,
  removeJobSidecar,
  resolveJobFile,
  resolveJobLogFile,
  stateHasEndedSession,
  updateState,
  upsertJob,
  withJobFileLock,
  writeJobFile
} from "./state.mjs";

export const SESSION_ID_ENV = "CODEX_COMPANION_SESSION_ID";
const TERMINAL_JOB_STATUSES = new Set(["completed", "failed", "cancelled"]);

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

function removeFileIfExists(filePath) {
  if (filePath && fs.existsSync(filePath)) {
    fs.unlinkSync(filePath);
  }
}

function withCurrentJobLog(job, logFile, callback, options = {}) {
  if (!logFile || !job?.workspaceRoot || !job?.id) {
    return false;
  }

  return withJobFileLock(job.workspaceRoot, job.id, () => {
    const jobFile = resolveJobFile(job.workspaceRoot, job.id);
    if (!fs.existsSync(jobFile)) {
      return false;
    }

    let storedJob = null;
    try {
      storedJob = readJobFile(jobFile);
    } catch {
      return false;
    }
    if (storedJob?.id !== job.id) {
      return false;
    }
    if (!options.allowTerminal && isTerminalJob(storedJob)) {
      return false;
    }
    if (hasEndedSession(job.workspaceRoot, storedJob.sessionId ?? job.sessionId)) {
      removeFileIfExists(jobFile);
      removeFileIfExists(logFile);
      return false;
    }
    if (!fs.existsSync(logFile)) {
      return false;
    }
    callback();
    return true;
  });
}

function appendProgressLogIfJobCurrent(job, logFile, event) {
  return withCurrentJobLog(job, logFile, () => {
    appendLogLine(logFile, event.message);
    appendLogBlock(logFile, event.logTitle, event.logBody);
  });
}

function appendLogBlockIfJobCurrent(job, logFile, title, body) {
  if (!body) {
    return false;
  }
  return withCurrentJobLog(job, logFile, () => appendLogBlock(logFile, title, body), { allowTerminal: true });
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

function isTerminalJob(job) {
  return TERMINAL_JOB_STATUSES.has(job?.status);
}

function readSharedJob(workspaceRoot, jobId) {
  try {
    return loadState(workspaceRoot).jobs.find((job) => job.id === jobId) ?? null;
  } catch {
    return null;
  }
}

function canAcceptProgressEvent(workspaceRoot, jobId, sharedJob = null) {
  if (isTerminalJob(sharedJob)) {
    return false;
  }

  try {
    const storedJob = readJobFile(resolveJobFile(workspaceRoot, jobId));
    if (!storedJob?.id || isTerminalJob(storedJob)) {
      return false;
    }
    return !cleanupTrackedJobIfSessionEnded(storedJob);
  } catch {
    return false;
  }
}

function removeOrphanProgressPatch(workspaceRoot, jobId, terminalJob = null, fallbackTerminalJob = null) {
  updateState(workspaceRoot, (state) => {
    const existing = state.jobs.find((job) => job.id === jobId);
    if (!existing) {
      return;
    }
    if (isTerminalJob(existing)) {
      const restoreJob = isTerminalJob(terminalJob) ? terminalJob : fallbackTerminalJob;
      if (restoreJob?.id === jobId && isTerminalJob(restoreJob)) {
        state.jobs = state.jobs.map((job) => (job.id === jobId ? sharedProgressJobPatch(restoreJob) : job));
      }
      return;
    }
    if (stateHasEndedSession(state, existing.sessionId)) {
      state.jobs = state.jobs.filter((job) => job.id !== jobId);
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
  }, { pruneJobFiles: false });
}

function removeTrackedJobAfterSessionEnd(job) {
  updateState(job.workspaceRoot, (state) => {
    state.jobs = state.jobs.filter((item) => item.id !== job.id);
  });
  removeJobSidecar(job.workspaceRoot, job);
}

function cleanupTrackedJobIfSessionEnded(job) {
  if (!job?.sessionId || !hasEndedSession(job.workspaceRoot, job.sessionId)) {
    return false;
  }
  removeTrackedJobAfterSessionEnd(job);
  return true;
}

function sessionEndedFinishError(job) {
  return new Error(`Claude session ${job.sessionId} ended before job ${job.id} could finish.`);
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
      return canAcceptProgressEvent(workspaceRoot, jobId);
    }

    const originalSharedJob = readSharedJob(workspaceRoot, jobId);
    if (!canAcceptProgressEvent(workspaceRoot, jobId, originalSharedJob)) {
      return false;
    }
    if (!upsertJob(workspaceRoot, patch)) {
      removeJobSidecar(workspaceRoot, { id: jobId });
      return false;
    }
    const updated = mutateJobFile(workspaceRoot, jobId, (storedJob) => {
      if (!storedJob?.id) {
        return null;
      }
      if (isTerminalJob(storedJob)) {
        return null;
      }
      return {
        ...storedJob,
        ...patch
      };
    });
    if (!updated) {
      let terminalJob = null;
      try {
        const storedJob = readJobFile(resolveJobFile(workspaceRoot, jobId));
        if (["completed", "failed", "cancelled"].includes(storedJob?.status)) {
          terminalJob = storedJob;
        }
      } catch {
        // Missing sidecars are handled by removing only the progress patch below.
      }
      removeOrphanProgressPatch(workspaceRoot, jobId, terminalJob, originalSharedJob);
      return false;
    }
    if (cleanupTrackedJobIfSessionEnded(updated)) {
      return false;
    }
    if (!upsertJob(workspaceRoot, sharedProgressJobPatch(updated))) {
      removeTrackedJobAfterSessionEnd(updated);
      return false;
    }
    return true;
  };
}

export function createProgressReporter({ stderr = false, logFile = null, onEvent = null, job = null } = {}) {
  if (!stderr && !logFile && !onEvent) {
    return null;
  }

  return (eventOrMessage) => {
    const event = normalizeProgressEvent(eventOrMessage);
    const jobBacked = Boolean(job?.workspaceRoot && job?.id);
    const shouldLog = onEvent?.(event);
    if (jobBacked && shouldLog === false) {
      return;
    }
    if (jobBacked && logFile) {
      if (!appendProgressLogIfJobCurrent(job, logFile, event)) {
        return;
      }
    }
    const stderrMessage = event.stderrMessage ?? event.message;
    if (stderr && stderrMessage) {
      process.stderr.write(`[codex] ${stderrMessage}\n`);
    }
    if (!jobBacked) {
      appendLogLine(logFile, event.message);
      appendLogBlock(logFile, event.logTitle, event.logBody);
    }
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
  const effectiveLogFile = options.logFile ?? job.logFile ?? null;
  const jobWithLog = {
    ...job,
    logFile: effectiveLogFile
  };
  if (cleanupTrackedJobIfSessionEnded(jobWithLog)) {
    throw new Error(`Claude session ${jobWithLog.sessionId} ended before job ${jobWithLog.id} could run.`);
  }

  const runningRecord = {
    ...jobWithLog,
    status: "running",
    startedAt: nowIso(),
    phase: "starting",
    pid: process.pid,
    logFile: effectiveLogFile
  };
  if (!upsertJob(job.workspaceRoot, runningRecord)) {
    removeTrackedJobAfterSessionEnd(runningRecord);
    throw new Error(`Claude session ${runningRecord.sessionId} ended before job ${runningRecord.id} could run.`);
  }
  const runningJobFile = writeJobFile(job.workspaceRoot, job.id, runningRecord);
  if (!runningJobFile) {
    removeTrackedJobAfterSessionEnd(runningRecord);
    throw new Error(`Claude session ${runningRecord.sessionId} ended before job ${runningRecord.id} could run.`);
  }
  if (process.env.CODEX_FOR_CLAUDE_DISABLE_HEARTBEAT === "1") {
    if (cleanupTrackedJobIfSessionEnded(runningRecord)) {
      throw new Error(`Claude session ${runningRecord.sessionId} ended before job ${runningRecord.id} could run.`);
    }
  } else if (!writeHeartbeatIfRunning(runningRecord)) {
    removeTrackedJobAfterSessionEnd(runningRecord);
    throw new Error(`Claude session ${runningRecord.sessionId} ended before job ${runningRecord.id} could run.`);
  }
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
    if (cleanupTrackedJobIfSessionEnded(runningRecord)) {
      throw sessionEndedFinishError(runningRecord);
    }
    if (!upsertJob(job.workspaceRoot, {
      id: job.id,
      sessionId: runningRecord.sessionId,
      status: completionStatus,
      threadId: execution.threadId ?? null,
      turnId: execution.turnId ?? null,
      summary: execution.summary,
      phase: completionStatus === "completed" ? "done" : "failed",
      pid: null,
      completedAt
    })) {
      removeTrackedJobAfterSessionEnd(runningRecord);
      throw sessionEndedFinishError(runningRecord);
    }
    const completedJobFile = writeJobFile(job.workspaceRoot, job.id, {
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
    if (!completedJobFile) {
      removeTrackedJobAfterSessionEnd(runningRecord);
      throw sessionEndedFinishError(runningRecord);
    }
    appendLogBlockIfJobCurrent(runningRecord, effectiveLogFile, "Final output", execution.rendered);
    if (cleanupTrackedJobIfSessionEnded(runningRecord)) {
      throw sessionEndedFinishError(runningRecord);
    }
    return execution;
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    heartbeatActive = false;
    if (heartbeat) {
      clearInterval(heartbeat);
      heartbeat = null;
    }
    if (cleanupTrackedJobIfSessionEnded(runningRecord)) {
      throw error;
    }
    const existing = readStoredJobOrNull(job.workspaceRoot, job.id) ?? runningRecord;
    const completedAt = nowIso();
    if (!upsertJob(job.workspaceRoot, {
      id: job.id,
      sessionId: runningRecord.sessionId,
      status: "failed",
      phase: "failed",
      pid: null,
      errorMessage,
      completedAt
    })) {
      removeTrackedJobAfterSessionEnd(runningRecord);
      throw error;
    }
    const failedRecord = {
      ...existing,
      status: "failed",
      phase: "failed",
      errorMessage,
      pid: null,
      completedAt,
      logFile: options.logFile ?? job.logFile ?? existing.logFile ?? null
    };
    const failedJobFile = writeJobFile(job.workspaceRoot, job.id, failedRecord);
    if (!failedJobFile) {
      removeTrackedJobAfterSessionEnd(failedRecord);
    }
    throw error;
  } finally {
    heartbeatActive = false;
    if (heartbeat) {
      clearInterval(heartbeat);
    }
  }
}
