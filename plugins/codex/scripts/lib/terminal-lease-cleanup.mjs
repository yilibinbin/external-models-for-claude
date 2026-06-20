import { listJobs } from "./state.mjs";
import { readStoredJob } from "./job-control.mjs";
import { releaseTerminalJobResourceLeasesForJobs } from "./resource-governor.mjs";

const TERMINAL_STATUSES = new Set(["completed", "failed", "cancelled"]);

function readStoredJobOrNull(workspaceRoot, jobId) {
  try {
    return readStoredJob(workspaceRoot, jobId);
  } catch {
    return null;
  }
}

export function releaseTerminalJobLeasesForWorkspace(workspaceRoot, env = process.env) {
  const terminalIds = new Set();
  for (const job of listJobs(workspaceRoot)) {
    const storedJob = readStoredJobOrNull(workspaceRoot, job.id);
    const status = storedJob?.status ?? job.status;
    if (TERMINAL_STATUSES.has(status)) {
      terminalIds.add(job.id);
    }
  }
  return releaseTerminalJobResourceLeasesForJobs(terminalIds, env);
}
