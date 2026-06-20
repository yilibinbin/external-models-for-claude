import { createResourceGovernor } from "./resource-governor-core.mjs";

const governor = createResourceGovernor({
  envPrefix: "CODEX_FOR_CLAUDE",
  defaultModelLimit: 2,
  defaultBackgroundLimit: 4,
  defaultStopGateLimit: 1,
  homeStateDir: ".claude/codex-for-claude/global-resource-locks",
  capacityLabel: "codex"
});

export const {
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
} = governor;
