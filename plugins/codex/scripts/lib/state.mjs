import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";

import { resolveWorkspaceRoot } from "./workspace.mjs";

const STATE_VERSION = 1;
const PLUGIN_DATA_ENV = "CLAUDE_PLUGIN_DATA";
const FALLBACK_STATE_ROOT_DIR = path.join(os.tmpdir(), "codex-companion");
const STATE_FILE_NAME = "state.json";
const JOBS_DIR_NAME = "jobs";
const MAX_JOBS = 50;
const MAX_ENDED_SESSIONS = 50;
const LOCK_STALE_AFTER_MS = 30000;
const FILE_LOCK_WAIT_ENV = "CODEX_FOR_CLAUDE_FILE_LOCK_WAIT_MS";
const DEFAULT_FILE_LOCK_WAIT_MS = LOCK_STALE_AFTER_MS + 5000;

export const LOCK_CONTEXT = {
  stateDepth: 0,
  jobDepth: 0
};

function nowIso() {
  return new Date().toISOString();
}

function defaultState() {
  return {
    version: STATE_VERSION,
    config: {
      stopReviewGate: false
    },
    endedSessions: [],
    jobs: []
  };
}

export function resolveStateDir(cwd) {
  const workspaceRoot = resolveWorkspaceRoot(cwd);
  let canonicalWorkspaceRoot = workspaceRoot;
  try {
    canonicalWorkspaceRoot = fs.realpathSync.native(workspaceRoot);
  } catch {
    canonicalWorkspaceRoot = workspaceRoot;
  }

  const slugSource = path.basename(workspaceRoot) || "workspace";
  const slug = slugSource.replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "workspace";
  const hash = createHash("sha256").update(canonicalWorkspaceRoot).digest("hex").slice(0, 16);
  const pluginDataDir = process.env[PLUGIN_DATA_ENV];
  const stateRoot = pluginDataDir ? path.join(pluginDataDir, "state") : FALLBACK_STATE_ROOT_DIR;
  return path.join(stateRoot, `${slug}-${hash}`);
}

export function resolveStateFile(cwd) {
  return path.join(resolveStateDir(cwd), STATE_FILE_NAME);
}

export function resolveJobsDir(cwd) {
  return path.join(resolveStateDir(cwd), JOBS_DIR_NAME);
}

export function ensureStateDir(cwd) {
  fs.mkdirSync(resolveJobsDir(cwd), { recursive: true });
}

export function loadState(cwd) {
  const stateFile = resolveStateFile(cwd);
  if (!fs.existsSync(stateFile)) {
    return defaultState();
  }

  try {
    const parsed = JSON.parse(fs.readFileSync(stateFile, "utf8"));
    return {
      ...defaultState(),
      ...parsed,
      config: {
        ...defaultState().config,
        ...(parsed.config ?? {})
      },
      endedSessions: normalizeEndedSessions(parsed.endedSessions),
      jobs: Array.isArray(parsed.jobs) ? parsed.jobs : []
    };
  } catch {
    return defaultState();
  }
}

function normalizeEndedSessions(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map((item) => String(item ?? "").trim()).filter(Boolean).slice(-MAX_ENDED_SESSIONS);
}

export function stateHasEndedSession(state, sessionId) {
  const normalizedSessionId = String(sessionId ?? "").trim();
  if (!normalizedSessionId) {
    return false;
  }
  return normalizeEndedSessions(state?.endedSessions).includes(normalizedSessionId);
}

export function markSessionEnded(state, sessionId) {
  const normalizedSessionId = String(sessionId ?? "").trim();
  if (!normalizedSessionId) {
    return;
  }
  const existing = normalizeEndedSessions(state.endedSessions).filter((item) => item !== normalizedSessionId);
  state.endedSessions = [...existing, normalizedSessionId].slice(-MAX_ENDED_SESSIONS);
}

export function hasEndedSession(cwd, sessionId) {
  return stateHasEndedSession(loadState(cwd), sessionId);
}

function pruneJobs(jobs) {
  return [...jobs]
    .sort((left, right) => String(right.updatedAt ?? "").localeCompare(String(left.updatedAt ?? "")))
    .slice(0, MAX_JOBS);
}

function removeFileIfExists(filePath) {
  if (filePath && fs.existsSync(filePath)) {
    fs.unlinkSync(filePath);
  }
}

function uniqueJobsById(jobs) {
  const byId = new Map();
  for (const job of jobs) {
    if (job?.id && !byId.has(job.id)) {
      byId.set(job.id, job);
    }
  }
  return [...byId.values()];
}

function sleepSync(ms) {
  const shared = new Int32Array(new SharedArrayBuffer(4));
  Atomics.wait(shared, 0, 0, ms);
}

function resolveFileLockWaitMs() {
  const rawValue = process.env[FILE_LOCK_WAIT_ENV];
  if (rawValue != null && rawValue !== "") {
    const parsed = Number(rawValue);
    if (Number.isFinite(parsed) && parsed >= 0) {
      return parsed;
    }
  }
  return DEFAULT_FILE_LOCK_WAIT_MS;
}

function acquireLock(lockDir) {
  const startedAt = Date.now();
  const waitMs = resolveFileLockWaitMs();
  while (true) {
    try {
      fs.mkdirSync(lockDir, { recursive: false });
      return () => {
        try {
          fs.rmdirSync(lockDir);
        } catch {
          // Lock cleanup is best-effort; a future stale-lock pass can recover.
        }
      };
    } catch (error) {
      if (error?.code !== "EEXIST") {
        throw error;
      }
      try {
        const stats = fs.statSync(lockDir);
        if (Date.now() - stats.mtimeMs > LOCK_STALE_AFTER_MS) {
          fs.rmdirSync(lockDir);
          continue;
        }
      } catch {
        continue;
      }
      if (Date.now() - startedAt > waitMs) {
        throw new Error(`Timed out acquiring lock ${lockDir}`);
      }
      sleepSync(20);
    }
  }
}

function stateLockDir(cwd) {
  return path.join(resolveStateDir(cwd), ".state.lock");
}

function jobLockDir(cwd, jobId) {
  const safeJobId = String(jobId).replace(/[^a-zA-Z0-9._-]+/g, "-") || "job";
  return path.join(resolveJobsDir(cwd), `.${safeJobId}.lock`);
}

export function withStateLock(cwd, callback) {
  if (LOCK_CONTEXT.jobDepth > 0) {
    throw new Error("state lock cannot be acquired while holding a job-file lock");
  }
  ensureStateDir(cwd);
  if (LOCK_CONTEXT.stateDepth > 0) {
    LOCK_CONTEXT.stateDepth += 1;
    try {
      return callback();
    } finally {
      LOCK_CONTEXT.stateDepth -= 1;
    }
  }

  const release = acquireLock(stateLockDir(cwd));
  LOCK_CONTEXT.stateDepth += 1;
  try {
    return callback();
  } finally {
    LOCK_CONTEXT.stateDepth -= 1;
    release();
  }
}

export function withJobFileLock(cwd, jobId, callback) {
  if (LOCK_CONTEXT.stateDepth > 0) {
    throw new Error("job-file lock cannot be acquired while holding a state lock");
  }
  if (LOCK_CONTEXT.jobDepth > 0) {
    throw new Error("job-file lock cannot be nested");
  }
  ensureStateDir(cwd);
  const release = acquireLock(jobLockDir(cwd, jobId));
  LOCK_CONTEXT.jobDepth += 1;
  try {
    return callback();
  } finally {
    LOCK_CONTEXT.jobDepth -= 1;
    release();
  }
}

export function writeAtomicJson(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  const tempFile = `${filePath}.${process.pid}.${Date.now()}.tmp`;
  fs.writeFileSync(tempFile, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  fs.renameSync(tempFile, filePath);
  return filePath;
}

export function saveStateUnlocked(cwd, state, previousJobs = []) {
  const nextJobs = pruneJobs(state.jobs ?? []);
  const current = loadState(cwd);
  const nextState = {
    version: STATE_VERSION,
    config: {
      ...defaultState().config,
      ...(state.config ?? {})
    },
    endedSessions: normalizeEndedSessions([
      ...normalizeEndedSessions(current.endedSessions),
      ...normalizeEndedSessions(state.endedSessions)
    ]),
    jobs: nextJobs
  };

  writeAtomicJson(resolveStateFile(cwd), nextState);
  return nextState;
}

export function removePrunedJobFiles(cwd, previousJobs, nextJobs) {
  if (process.env.CODEX_FOR_CLAUDE_SKIP_STATE_PRUNE === "1") {
    return;
  }
  const retainedIds = new Set((nextJobs ?? []).map((job) => job.id));
  for (const job of previousJobs) {
    if (retainedIds.has(job.id)) {
      continue;
    }
    withJobFileLock(cwd, job.id, () => {
      const currentState = loadState(cwd);
      if ((currentState.jobs ?? []).some((currentJob) => currentJob.id === job.id)) {
        return;
      }
      const jobFile = resolveJobFile(cwd, job.id);
      let storedLogFile = null;
      try {
        const storedJob = readJobFile(jobFile);
        storedLogFile = storedJob?.logFile ?? null;
        if (storedJob?.status === "queued" || storedJob?.status === "running") {
          return;
        }
      } catch {
        // Missing or corrupt job files can still be removed from the sidecar set.
      }
      removeJobFile(jobFile);
      removeFileIfExists(storedLogFile);
      removeFileIfExists(job.logFile);
    });
  }
}

export function saveState(cwd, state) {
  let previousJobs = [];
  const nextState = withStateLock(cwd, () => {
    previousJobs = uniqueJobsById([...loadState(cwd).jobs, ...listJobSidecars(cwd)]);
    return saveStateUnlocked(cwd, state, previousJobs);
  });
  removePrunedJobFiles(cwd, previousJobs, nextState.jobs);

  return nextState;
}

export function updateState(cwd, mutator, options = {}) {
  let nextState;
  let prunedPreviousJobs = [];
  nextState = withStateLock(cwd, () => {
    const current = loadState(cwd);
    const previousJobs = current.jobs.slice();
    prunedPreviousJobs = previousJobs;
    mutator(current);
    nextState = saveStateUnlocked(cwd, current, previousJobs);
    return nextState;
  });
  if (options.pruneJobFiles !== false) {
    removePrunedJobFiles(cwd, prunedPreviousJobs, nextState.jobs);
  }

  return nextState;
}

export function generateJobId(prefix = "job") {
  const random = Math.random().toString(36).slice(2, 8);
  return `${prefix}-${Date.now().toString(36)}-${random}`;
}

export function upsertJob(cwd, jobPatch) {
  let applied = false;
  updateState(cwd, (state) => {
    const timestamp = nowIso();
    const existingIndex = state.jobs.findIndex((job) => job.id === jobPatch.id);
    const existing = existingIndex === -1 ? null : state.jobs[existingIndex];
    const sessionId = jobPatch.sessionId ?? existing?.sessionId ?? null;
    if (stateHasEndedSession(state, sessionId)) {
      state.jobs = state.jobs.filter((job) => job.id !== jobPatch.id);
      return;
    }
    if (existingIndex === -1) {
      state.jobs.unshift({
        createdAt: timestamp,
        updatedAt: timestamp,
        ...jobPatch
      });
      applied = true;
      return;
    }
    state.jobs[existingIndex] = {
      ...state.jobs[existingIndex],
      ...jobPatch,
      updatedAt: timestamp
    };
    applied = true;
  });
  return applied;
}

export function listJobs(cwd) {
  return loadState(cwd).jobs;
}

export function setConfig(cwd, key, value) {
  return updateState(cwd, (state) => {
    state.config = {
      ...state.config,
      [key]: value
    };
  });
}

export function getConfig(cwd) {
  return loadState(cwd).config;
}

export function writeJobFile(cwd, jobId, payload) {
  return withJobFileLock(cwd, jobId, () => {
    const jobFile = resolveJobFile(cwd, jobId);
    if (hasEndedSession(cwd, payload?.sessionId)) {
      const logFiles = new Set();
      if (payload?.logFile) {
        logFiles.add(payload.logFile);
      }
      try {
        const storedJob = readJobFile(jobFile);
        if (storedJob?.logFile) {
          logFiles.add(storedJob.logFile);
        }
      } catch {
        // Missing or corrupt sidecars are still safe to delete best-effort.
      }
      removeJobFile(jobFile);
      for (const logFile of logFiles) {
        removeFileIfExists(logFile);
      }
      return null;
    }
    return writeAtomicJson(jobFile, payload);
  });
}

export function readJobFile(jobFile) {
  return JSON.parse(fs.readFileSync(jobFile, "utf8"));
}

export function listJobSidecars(cwd) {
  ensureStateDir(cwd);
  return fs.readdirSync(resolveJobsDir(cwd))
    .filter((name) => name.endsWith(".json"))
    .map((name) => {
      try {
        const job = readJobFile(path.join(resolveJobsDir(cwd), name));
        return job?.id ? job : null;
      } catch {
        return null;
      }
    })
    .filter(Boolean);
}

export function mutateJobFile(cwd, jobId, mutate) {
  return withJobFileLock(cwd, jobId, () => {
    const jobFile = resolveJobFile(cwd, jobId);
    if (!fs.existsSync(jobFile)) {
      return null;
    }
    const current = readJobFile(jobFile);
    if (hasEndedSession(cwd, current?.sessionId)) {
      removeJobFile(jobFile);
      removeFileIfExists(current?.logFile);
      return null;
    }
    const next = mutate(current);
    if (next == null) {
      return null;
    }
    if (hasEndedSession(cwd, next?.sessionId)) {
      removeJobFile(jobFile);
      removeFileIfExists(next?.logFile ?? current?.logFile);
      return null;
    }
    writeAtomicJson(jobFile, next);
    return next;
  });
}

export function removeJobSidecar(cwd, job) {
  return withJobFileLock(cwd, job.id, () => {
    const jobFile = resolveJobFile(cwd, job.id);
    const logFiles = new Set();
    if (job.logFile) {
      logFiles.add(job.logFile);
    }
    try {
      const storedJob = readJobFile(jobFile);
      if (storedJob?.logFile) {
        logFiles.add(storedJob.logFile);
      }
    } catch {
      // Missing or corrupt sidecars are still safe to delete best-effort.
    }
    removeJobFile(jobFile);
    for (const logFile of logFiles) {
      removeFileIfExists(logFile);
    }
  });
}

function removeJobFile(jobFile) {
  if (fs.existsSync(jobFile)) {
    fs.unlinkSync(jobFile);
  }
}

export function resolveJobLogFile(cwd, jobId) {
  ensureStateDir(cwd);
  return path.join(resolveJobsDir(cwd), `${jobId}.log`);
}

export function resolveJobFile(cwd, jobId) {
  ensureStateDir(cwd);
  return path.join(resolveJobsDir(cwd), `${jobId}.json`);
}
