// This resource governor is ported from fanghao's Gemini/Antigravity governor work covered by this repository's root MIT license with Codex-specific additions.

import { randomBytes } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";

const PLUGIN_DATA_ENV = "CLAUDE_PLUGIN_DATA";
const DEFAULT_MUTEX_WAIT_MS = 30_000;
const DEFAULT_LOCK_STALE_MS = 30_000;
const DEFAULT_LEASE_TTL_MS = 24 * 60 * 60 * 1000;
const UNCLAIMED_WITHOUT_OWNER_TTL_MS = 5 * 60 * 1000;
const TRANSFER_CLAIM_GRACE_MS = 30_000;

function sleepMs(ms) {
  if (
    typeof Atomics !== "undefined" &&
    typeof SharedArrayBuffer !== "undefined" &&
    typeof Atomics.wait === "function"
  ) {
    Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, Math.max(0, ms));
    return;
  }
  const deadline = Date.now() + Math.max(0, ms);
  while (Date.now() < deadline) {
    // Synchronous fallback for JS runtimes without Atomics.wait.
  }
}

function parseInteger(value, fallback, { min = 0, max = 64 } = {}) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < min) {
    return fallback;
  }
  return Math.min(Math.trunc(parsed), max);
}

function iso(ms) {
  return new Date(ms).toISOString();
}

function processAlive(pid) {
  const numericPid = Number(pid);
  if (!Number.isInteger(numericPid) || numericPid <= 0) {
    return false;
  }
  try {
    process.kill(numericPid, 0);
    return true;
  } catch (error) {
    return error?.code === "EPERM";
  }
}

function validLeaseId(leaseId) {
  return /^[A-Za-z0-9._-]+$/.test(String(leaseId || ""));
}

function readJsonOrNull(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

function writeJsonAtomic(file, value) {
  const tmp = `${file}.${process.pid}.${randomBytes(4).toString("hex")}.tmp`;
  fs.writeFileSync(tmp, `${JSON.stringify(value, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  fs.renameSync(tmp, file);
}

export function createResourceGovernor(config) {
  const envPrefix = String(config.envPrefix || "");
  const capacityLabel = String(config.capacityLabel || "resource");
  const disableEnv = `${envPrefix}_RESOURCE_GOVERNOR`;
  const lockDirEnv = `${envPrefix}_RESOURCE_LOCK_DIR`;
  const modelLimitEnv = `${envPrefix}_GLOBAL_MAX_MODEL_CALLS`;
  const backgroundLimitEnv = `${envPrefix}_GLOBAL_MAX_BACKGROUND_JOBS`;
  const stopGateLimitEnv = `${envPrefix}_GLOBAL_MAX_STOP_GATES`;
  const mutexWaitEnv = `${envPrefix}_MUTEX_WAIT_MS`;
  const lockStaleEnv = `${envPrefix}_LOCK_STALE_MS`;
  const homeStateDir = String(config.homeStateDir || ".resource-governor/global-resource-locks");

  function governorDisabled(env = process.env) {
    return String(env[disableEnv] || "").toLowerCase() === "off";
  }

  function resourceLockRoot(env = process.env) {
    if (env[lockDirEnv]) {
      return path.resolve(env[lockDirEnv]);
    }
    if (env[PLUGIN_DATA_ENV]) {
      return path.join(path.resolve(env[PLUGIN_DATA_ENV]), "global-resource-locks");
    }
    return path.join(os.homedir(), homeStateDir);
  }

  function ensureRoot(env = process.env) {
    const root = resourceLockRoot(env);
    fs.mkdirSync(root, { recursive: true, mode: 0o700 });
    return root;
  }

  function leasePath(root, leaseId) {
    if (!validLeaseId(leaseId)) {
      throw new Error("Invalid resource lease id.");
    }
    return path.join(root, `${leaseId}.json`);
  }

  function mutexWaitMs(env = process.env) {
    return parseInteger(env[mutexWaitEnv], DEFAULT_MUTEX_WAIT_MS, { min: 0, max: 10 * 60 * 1000 });
  }

  function lockStaleMs(env = process.env) {
    return parseInteger(env[lockStaleEnv], DEFAULT_LOCK_STALE_MS, { min: 1000, max: 10 * 60 * 1000 });
  }

  function resourceLimit(kind, env = process.env) {
    if (kind === "background-job") {
      return parseInteger(env[backgroundLimitEnv], config.defaultBackgroundLimit ?? 4, { min: 0, max: 128 });
    }
    if (kind === "stop-gate") {
      return parseInteger(env[stopGateLimitEnv], config.defaultStopGateLimit ?? 1, { min: 0, max: 128 });
    }
    return parseInteger(env[modelLimitEnv], config.defaultModelLimit ?? 2, { min: 0, max: 128 });
  }

  function acquireMutex(root, env = process.env) {
    const file = path.join(root, ".governor.lock");
    const deadline = Date.now() + mutexWaitMs(env);
    while (Date.now() <= deadline) {
      try {
        const handle = fs.openSync(file, "wx", 0o600);
        fs.writeFileSync(handle, JSON.stringify({ pid: process.pid, createdAtMs: Date.now() }));
        return { handle, file };
      } catch (error) {
        if (error.code !== "EEXIST") {
          throw error;
        }
        try {
          const stat = fs.statSync(file);
          const lock = readJsonOrNull(file);
          if (lock && ((Date.now() - stat.mtimeMs) > lockStaleMs(env) || !processAlive(lock.pid))) {
            fs.rmSync(file, { force: true });
            continue;
          }
        } catch (statError) {
          if (statError.code !== "ENOENT") {
            throw statError;
          }
          continue;
        }
        if (Date.now() >= deadline) {
          return null;
        }
        sleepMs(25);
      }
    }
    return null;
  }

  function releaseMutex(lock) {
    if (!lock) {
      return;
    }
    try {
      fs.closeSync(lock.handle);
    } catch {
      // Ignore close failures; unlink below controls future waiters.
    }
    try {
      fs.rmSync(lock.file, { force: true });
    } catch {
      // Best-effort cleanup only.
    }
  }

  function isOurLease(lease) {
    return lease?.label === capacityLabel;
  }

  function leaseAgeMs(lease, now) {
    const createdAtMs = Number(lease?.createdAtMs);
    if (Number.isFinite(createdAtMs)) {
      return now - createdAtMs;
    }
    const parsed = Date.parse(String(lease?.createdAt || ""));
    return Number.isFinite(parsed) ? now - parsed : Number.POSITIVE_INFINITY;
  }

  function transferAgeMs(lease, now) {
    const transferredAtMs = Number(lease?.transferredAtMs);
    if (Number.isFinite(transferredAtMs)) {
      return now - transferredAtMs;
    }
    const parsed = Date.parse(String(lease?.transferredAt || ""));
    return Number.isFinite(parsed) ? now - parsed : Number.POSITIVE_INFINITY;
  }

  function isStaleLease(lease, now = Date.now()) {
    if (!lease || !isOurLease(lease) || !lease.id || !lease.kind) {
      return true;
    }
    if (leaseAgeMs(lease, now) >= DEFAULT_LEASE_TTL_MS) {
      return true;
    }

    const pid = Number(lease.pid);
    const ownerPid = Number(lease.ownerPid);
    const hasOwner = Number.isInteger(ownerPid) && ownerPid > 0;
    const ownerLive = hasOwner && processAlive(ownerPid);
    const unclaimed = !Number.isInteger(pid) || pid <= 0;

    if (unclaimed) {
      if (hasOwner) {
        return !ownerLive;
      }
      return leaseAgeMs(lease, now) >= UNCLAIMED_WITHOUT_OWNER_TTL_MS;
    }

    if (lease.transferredAtMs || lease.transferredAt) {
      if (transferAgeMs(lease, now) < TRANSFER_CLAIM_GRACE_MS) {
        return false;
      }
    }
    return !processAlive(pid);
  }

  function reapStaleResourceLeases(env = process.env, options = {}) {
    if (governorDisabled(env)) {
      return 0;
    }
    const root = ensureRoot(env);
    const mutex = acquireMutex(root, env);
    if (!mutex) {
      return 0;
    }
    try {
      return reapStaleResourceLeasesLocked(root, options);
    } finally {
      releaseMutex(mutex);
    }
  }

  function reapStaleResourceLeasesLocked(root, options = {}) {
    let removed = 0;
    let names = [];
    try {
      names = fs.readdirSync(root);
    } catch {
      return 0;
    }
    const now = Date.now();
    for (const name of names) {
      if (!name.endsWith(".json")) {
        continue;
      }
      const file = path.join(root, name);
      const lease = readJsonOrNull(file);
      if (lease?.id && lease.id === options.exemptId) {
        continue;
      }
      if (!lease || (isOurLease(lease) && isStaleLease(lease, now))) {
        try {
          fs.rmSync(file, { force: true });
          removed += 1;
        } catch {
          // Best-effort cleanup only.
        }
      }
    }
    return removed;
  }

  function activeLeasesLocked(root, kind) {
    reapStaleResourceLeasesLocked(root);
    let names = [];
    try {
      names = fs.readdirSync(root);
    } catch {
      return [];
    }
    return names
      .filter((name) => name.endsWith(".json"))
      .map((name) => readJsonOrNull(path.join(root, name)))
      .filter((lease) => isOurLease(lease) && lease.kind === kind && !isStaleLease(lease));
  }

  function releaseResourceLease(leaseId, env = process.env) {
    if (!leaseId || governorDisabled(env)) {
      return;
    }
    try {
      fs.rmSync(leasePath(resourceLockRoot(env), leaseId), { force: true });
    } catch {
      // Best-effort cleanup only.
    }
  }

  function makeLeaseResult(lease, root, env) {
    return {
      ok: true,
      lease,
      root,
      release() {
        releaseResourceLease(lease.id, env);
      }
    };
  }

  function acquireResourceLease(kind, options = {}) {
    const env = options.env || process.env;
    if (governorDisabled(env)) {
      return { ok: true, disabled: true, release() {} };
    }
    const root = ensureRoot(env);
    const limit = Number.isInteger(options.limit) ? options.limit : resourceLimit(kind, env);
    const mutex = acquireMutex(root, env);
    if (!mutex) {
      return {
        ok: false,
        reason: "resource governor lock is busy",
        kind,
        active: 0,
        limit
      };
    }
    try {
      const active = activeLeasesLocked(root, kind);
      if (active.length >= limit) {
        return {
          ok: false,
          reason: `global ${kind} capacity exhausted`,
          kind,
          active: active.length,
          limit
        };
      }
      const now = Date.now();
      const id = `${kind}-${now.toString(36)}-${process.pid}-${randomBytes(6).toString("hex")}`;
      const lease = {
        id,
        label: capacityLabel,
        kind,
        command: String(options.command || ""),
        jobId: options.jobId ? String(options.jobId) : null,
        pid: Number.isInteger(options.pid) ? options.pid : process.pid,
        ppid: process.ppid,
        ownerPid: process.pid,
        transferable: Boolean(options.transferable),
        createdAt: iso(now),
        createdAtMs: now,
        updatedAt: iso(now),
        updatedAtMs: now
      };
      fs.writeFileSync(leasePath(root, id), `${JSON.stringify(lease, null, 2)}\n`, {
        encoding: "utf8",
        mode: 0o600,
        flag: "wx"
      });
      return makeLeaseResult(lease, root, env);
    } finally {
      releaseMutex(mutex);
    }
  }

  function readClaimableLeaseLocked(root, leaseId, kind) {
    if (!validLeaseId(leaseId)) {
      return null;
    }
    const lease = readJsonOrNull(leasePath(root, leaseId));
    if (!isOurLease(lease) || lease.kind !== kind || !lease.transferable || lease.claimedAt || lease.claimedAtMs || isStaleLease(lease)) {
      return null;
    }
    return lease;
  }

  function failedClaimLeaseStateLocked(root, leaseId, kind) {
    if (!validLeaseId(leaseId)) {
      return null;
    }
    const lease = readJsonOrNull(leasePath(root, leaseId));
    if (!isOurLease(lease) || lease.kind !== kind) {
      return null;
    }
    return {
      exists: true,
      kind,
      transferable: Boolean(lease.transferable),
      claimed: Boolean(lease.claimedAt || lease.claimedAtMs || lease.transferable === false),
      stale: isStaleLease(lease)
    };
  }

  function claimResourceLease(leaseId, kind, env = process.env) {
    if (governorDisabled(env)) {
      return { ok: true, disabled: true, release() {} };
    }
    const root = ensureRoot(env);
    const mutex = acquireMutex(root, env);
    if (!mutex) {
      return { ok: false, reason: "resource governor lock is busy", kind, active: 0, limit: resourceLimit(kind, env) };
    }
    try {
      reapStaleResourceLeasesLocked(root, { exemptId: leaseId });
      const leaseState = failedClaimLeaseStateLocked(root, leaseId, kind);
      const lease = readClaimableLeaseLocked(root, leaseId, kind);
      if (!lease) {
        return {
          ok: false,
          reason: "lease is not claimable",
          kind,
          active: activeLeasesLocked(root, kind).length,
          limit: resourceLimit(kind, env),
          leaseState
        };
      }
      const now = Date.now();
      const updated = {
        ...lease,
        pid: process.pid,
        ppid: process.ppid,
        ownerPid: process.pid,
        transferable: false,
        updatedAt: iso(now),
        updatedAtMs: now,
        claimedAt: iso(now),
        claimedAtMs: now
      };
      writeJsonAtomic(leasePath(root, leaseId), updated);
      return makeLeaseResult(updated, root, env);
    } finally {
      releaseMutex(mutex);
    }
  }

  function transferResourceLease(leaseId, pid, env = process.env, options = {}) {
    if (governorDisabled(env)) {
      return true;
    }
    if (!leaseId || !validLeaseId(leaseId)) {
      return false;
    }
    const root = ensureRoot(env);
    const mutex = acquireMutex(root, env);
    if (!mutex) {
      return false;
    }
    try {
      const file = leasePath(root, leaseId);
      const lease = readJsonOrNull(file);
      if (!isOurLease(lease)) {
        return false;
      }
      const numericPid = Number(pid);
      if (!Number.isInteger(numericPid) || numericPid <= 0) {
        return false;
      }
      if (lease.claimedAt || lease.claimedAtMs) {
        return Number(lease.pid) === numericPid;
      }
      if (lease.transferable === false) {
        return false;
      }
      const now = Date.now();
      writeJsonAtomic(file, {
        ...lease,
        pid: numericPid,
        ppid: process.pid,
        transferable: Boolean(options.keepTransferable),
        transferredAt: iso(now),
        transferredAtMs: now,
        updatedAt: iso(now),
        updatedAtMs: now
      });
      return true;
    } finally {
      releaseMutex(mutex);
    }
  }

  function ensureResourceLease(leaseId, kind, options = {}) {
    const env = options.env || process.env;
    if (governorDisabled(env)) {
      return { ok: true, disabled: true, release() {} };
    }
    if (leaseId && validLeaseId(leaseId)) {
      const root = ensureRoot(env);
      const mutex = acquireMutex(root, env);
      if (!mutex) {
        return { ok: false, reason: "resource governor lock is busy", kind, active: 0, limit: resourceLimit(kind, env) };
      }
      try {
        reapStaleResourceLeasesLocked(root, { exemptId: leaseId });
        const lease = readJsonOrNull(leasePath(root, leaseId));
        if (isOurLease(lease) && lease.kind === kind && !isStaleLease(lease)) {
          return makeLeaseResult(lease, root, env);
        }
      } finally {
        releaseMutex(mutex);
      }
    }
    return acquireResourceLease(kind, options);
  }

  function verifyResourceLease(leaseId, kind, options = {}) {
    const env = options.env || process.env;
    if (governorDisabled(env)) {
      return { ok: true, disabled: true };
    }
    if (!leaseId || !validLeaseId(leaseId)) {
      return { ok: false, reason: "lease missing" };
    }
    const root = resourceLockRoot(env);
    const lease = readJsonOrNull(leasePath(root, leaseId));
    if (!isOurLease(lease)) {
      return { ok: false, reason: "lease missing" };
    }
    if (lease.kind !== kind) {
      return { ok: false, reason: "lease kind mismatch" };
    }
    const expectedCommand = options.expectedCommand ?? options.command;
    if (expectedCommand != null && String(expectedCommand) !== String(lease.command || "")) {
      return { ok: false, reason: "lease command mismatch" };
    }
    if (options.expectedPid != null && Number(options.expectedPid) !== Number(lease.pid)) {
      return { ok: false, reason: "lease pid mismatch" };
    }
    const parentPid = Number(lease.ownerPid);
    if (options.expectedParentPid != null && Number(options.expectedParentPid) !== parentPid) {
      return { ok: false, reason: "lease parent mismatch" };
    }
    if (options.expectedOwnerPid != null && Number(options.expectedOwnerPid) !== Number(lease.ownerPid)) {
      return { ok: false, reason: "lease owner mismatch" };
    }
    if (leaseAgeMs(lease, Date.now()) >= DEFAULT_LEASE_TTL_MS) {
      return { ok: false, reason: "lease stale" };
    }
    const pidToCheck = Number(options.expectedPid ?? lease.pid);
    if (Number.isInteger(pidToCheck) && pidToCheck > 0 && !processAlive(pidToCheck)) {
      return { ok: false, reason: "lease parent not alive" };
    }
    if (options.expectedParentPid != null && Number.isInteger(parentPid) && parentPid > 0 && !processAlive(parentPid)) {
      return { ok: false, reason: "lease parent not alive" };
    }
    const ownerToCheck = Number(options.expectedOwnerPid ?? lease.ownerPid);
    if (Number.isInteger(ownerToCheck) && ownerToCheck > 0 && !processAlive(ownerToCheck)) {
      return { ok: false, reason: "lease parent not alive" };
    }
    if (isStaleLease(lease)) {
      return { ok: false, reason: "lease stale" };
    }
    return { ok: true, lease };
  }

  function releaseTerminalJobResourceLeasesForJobs(jobIds, env = process.env) {
    if (governorDisabled(env)) {
      return 0;
    }
    const ids = new Set([...jobIds].map((id) => String(id)));
    if (ids.size === 0) {
      return 0;
    }
    const root = ensureRoot(env);
    const mutex = acquireMutex(root, env);
    if (!mutex) {
      return 0;
    }
    try {
      let removed = 0;
      let names = [];
      try {
        names = fs.readdirSync(root);
      } catch {
        return 0;
      }
      for (const name of names) {
        if (!name.endsWith(".json")) {
          continue;
        }
        const file = path.join(root, name);
        const lease = readJsonOrNull(file);
        if (isOurLease(lease) && lease.kind === "background-job" && lease.jobId && ids.has(String(lease.jobId))) {
          fs.rmSync(file, { force: true });
          removed += 1;
        }
      }
      return removed;
    } finally {
      releaseMutex(mutex);
    }
  }

  function capacityBlockedMessage(lease) {
    return `capacity_blocked: ${capacityLabel} ${lease.kind} capacity is full (${lease.active}/${lease.limit}); wait for existing work to finish or lower concurrency.`;
  }

  function capacityBlockedResult(lease) {
    return {
      status: 75,
      stdout: "",
      stderr: `${capacityBlockedMessage(lease)}\n`,
      error: capacityBlockedMessage(lease),
      errorCode: "ECAPACITY"
    };
  }

  async function withResourceLease(kind, options, callback) {
    const lease = acquireResourceLease(kind, options);
    if (!lease.ok) {
      const error = new Error(capacityBlockedMessage(lease));
      error.status = 75;
      error.code = "ECAPACITY";
      error.result = capacityBlockedResult(lease);
      throw error;
    }
    try {
      return await callback(lease);
    } finally {
      lease.release();
    }
  }

  return {
    acquireResourceLease,
    claimResourceLease,
    transferResourceLease,
    ensureResourceLease,
    verifyResourceLease,
    releaseTerminalJobResourceLeasesForJobs,
    releaseResourceLease,
    reapStaleResourceLeases,
    withResourceLease,
    capacityBlockedResult,
    capacityBlockedMessage,
    resourceLockRoot,
    resourceLimit
  };
}
