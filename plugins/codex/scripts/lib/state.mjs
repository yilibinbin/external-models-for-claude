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
const LOCK_STALE_AFTER_MS = 30000;

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
      jobs: Array.isArray(parsed.jobs) ? parsed.jobs : []
    };
  } catch {
    return defaultState();
  }
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

function sleepSync(ms) {
  const shared = new Int32Array(new SharedArrayBuffer(4));
  Atomics.wait(shared, 0, 0, ms);
}

function acquireLock(lockDir) {
  const startedAt = Date.now();
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
      if (Date.now() - startedAt > LOCK_STALE_AFTER_MS) {
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

export function saveStateUnlocked(cwd, state) {
  const nextJobs = pruneJobs(state.jobs ?? []);
  const nextState = {
    version: STATE_VERSION,
    config: {
      ...defaultState().config,
      ...(state.config ?? {})
    },
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
    removeJobFile(resolveJobFile(cwd, job.id));
    removeFileIfExists(job.logFile);
  }
}

export function saveState(cwd, state) {
  let previousJobs = [];
  const nextState = withStateLock(cwd, () => {
    previousJobs = loadState(cwd).jobs;
    return saveStateUnlocked(cwd, state);
  });

  removePrunedJobFiles(cwd, previousJobs, nextState.jobs);
  return nextState;
}

export function updateState(cwd, mutate) {
  let previousJobs = [];
  const nextState = withStateLock(cwd, () => {
    const state = loadState(cwd);
    previousJobs = state.jobs;
    mutate(state);
    return saveStateUnlocked(cwd, state);
  });

  removePrunedJobFiles(cwd, previousJobs, nextState.jobs);
  return nextState;
}

export function generateJobId(prefix = "job") {
  const random = Math.random().toString(36).slice(2, 8);
  return `${prefix}-${Date.now().toString(36)}-${random}`;
}

export function upsertJob(cwd, jobPatch) {
  return updateState(cwd, (state) => {
    const timestamp = nowIso();
    const existingIndex = state.jobs.findIndex((job) => job.id === jobPatch.id);
    if (existingIndex === -1) {
      state.jobs.unshift({
        createdAt: timestamp,
        updatedAt: timestamp,
        ...jobPatch
      });
      return;
    }
    state.jobs[existingIndex] = {
      ...state.jobs[existingIndex],
      ...jobPatch,
      updatedAt: timestamp
    };
  });
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
  return withJobFileLock(cwd, jobId, () => writeAtomicJson(resolveJobFile(cwd, jobId), payload));
}

export function readJobFile(jobFile) {
  return JSON.parse(fs.readFileSync(jobFile, "utf8"));
}

export function mutateJobFile(cwd, jobId, mutate) {
  return withJobFileLock(cwd, jobId, () => {
    const jobFile = resolveJobFile(cwd, jobId);
    if (!fs.existsSync(jobFile)) {
      return null;
    }
    const current = readJobFile(jobFile);
    const next = mutate(current);
    if (next == null) {
      return null;
    }
    writeAtomicJson(jobFile, next);
    return next;
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
