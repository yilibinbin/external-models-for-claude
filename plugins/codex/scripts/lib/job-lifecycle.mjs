import process from "node:process";

export const JOB_HEARTBEAT_INTERVAL_MS = 15000;
export const JOB_SUSPECT_AFTER_MS = 180000;
export const JOB_LOST_AFTER_MS = 1200000;

function defaultIsProcessAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) {
    return true;
  }

  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function resolveNowMs(options) {
  if (Number.isFinite(options.nowMs)) {
    return options.nowMs;
  }
  if (options.now instanceof Date) {
    return options.now.getTime();
  }
  if (typeof options.now === "string") {
    const parsed = Date.parse(options.now);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  if (Number.isFinite(options.now)) {
    return options.now;
  }
  return Date.now();
}

function resolveHeartbeatMs(job) {
  if (Number.isFinite(job?.heartbeatAtMs)) {
    return job.heartbeatAtMs;
  }
  const updatedAt = Date.parse(job?.updatedAt ?? "");
  if (Number.isFinite(updatedAt)) {
    return updatedAt;
  }
  return null;
}

export function classifyJobLiveness(job, options = {}) {
  const status = job?.status ?? "unknown";
  if (status !== "queued" && status !== "running") {
    return { state: "terminal", reason: status };
  }

  const nowMs = resolveNowMs(options);
  const heartbeatMs = resolveHeartbeatMs(job);
  const ageMs = heartbeatMs == null ? Number.POSITIVE_INFINITY : Math.max(0, nowMs - heartbeatMs);
  const isProcessAlive = options.isProcessAlive ?? defaultIsProcessAlive;
  const processAlive = isProcessAlive(job?.pid);

  if (!processAlive) {
    return {
      state: ageMs >= JOB_LOST_AFTER_MS ? "lost" : "suspect",
      reason: "process-not-alive"
    };
  }

  if (ageMs >= JOB_LOST_AFTER_MS) {
    return { state: "lost", reason: "heartbeat-lost" };
  }
  if (ageMs >= JOB_SUSPECT_AFTER_MS) {
    return { state: "suspect", reason: "heartbeat-stale" };
  }
  return { state: "healthy", reason: "heartbeat-current" };
}
