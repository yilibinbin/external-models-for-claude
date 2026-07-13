// Dispatch: translate one logical review intent into a specific reviewer's invocation,
// and run it the way that reviewer requires. Two hard constraints from operating the
// panel by hand:
//   1. The codex reviewer's liveness gate aborts any job that inherits the host session
//      id, so its child env must have CODEX_COMPANION_SESSION_ID and CLAUDE_CODE_SESSION_ID
//      UNSET (equivalent to the `env -u ...` prefix). The broader CLAUDE_CODE_* / CLAUDECODE
//      vars must stay — auth lives there.
//   2. Reviews are app-server-backed and take minutes, so they run DETACHED; the caller
//      waits on the PID. Reviewers run one at a time (the skill enforces serial order).

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// Session-scoped env the codex reviewer must not inherit (else its liveness gate aborts).
const CODEX_SESSION_ENV = ["CODEX_COMPANION_SESSION_ID", "CLAUDE_CODE_SESSION_ID"];

// Orchestration artifacts (reviewer output, pid, ledger) live OUTSIDE the target repo.
// A reviewer with no --scope (antigravity) reviews the full working tree, so an artifact
// left in the repo would be reviewed as part of the diff — self-referential and noisy.
export function defaultArtifactDir() {
  return path.join(os.tmpdir(), "review-chain");
}

export function defaultOutFile(pluginName) {
  return path.join(defaultArtifactDir(), `${pluginName}.out`);
}

// Build the invocation plan for one reviewer without running it. Pure + fully testable.
// `name` is the CANONICAL plugin key (e.g. "codex"); codex-specific behavior keys off it,
// never off raw caller input, so passing the accepted "codex@marketplace" id form still
// triggers the session-env unset. Falls back to `plugin` for callers that pass a bare name.
export function buildDispatchPlan({ plugin, name, companion, adapter, scope, base, quality, focus }) {
  const canonical = name ?? plugin;
  const isCodex = canonical === "codex";
  const argv = [companion, "adversarial-review"];

  if (adapter.supportsScope && scope) {
    argv.push("--scope", scope);
  }
  if (adapter.supportsBase && base) {
    argv.push("--base", base);
  }
  if (adapter.jsonFlag) {
    argv.push(adapter.jsonFlag);
  }
  // Strength is codex-only (--quality); other reviewers ignore/reject it.
  if (quality && isCodex) {
    argv.push("--quality", quality);
  }
  // Focus prose travels after `--` as discrete argv tokens — never interpolated into a shell.
  const focusTokens = Array.isArray(focus) ? focus.filter((t) => t !== undefined && t !== "") : [];
  if (focusTokens.length) {
    argv.push("--", ...focusTokens);
  }

  // Only the codex reviewer needs the session-env unset (its liveness gate).
  const unsetEnv = isCodex ? [...CODEX_SESSION_ENV] : [];

  return {
    plugin: canonical,
    argv,
    unsetEnv,
    detached: true
  };
}

// Execute a plan detached, routing output to a file, and record the PID so the caller can
// wait on it. Never runs inline (reviews take minutes; the 2-minute Bash cap would kill it).
export function runDispatch(plan, { cwd, outFile, pidFile }) {
  const env = { ...process.env };
  for (const key of plan.unsetEnv) {
    delete env[key];
  }
  fs.mkdirSync(path.dirname(outFile), { recursive: true });
  const out = fs.openSync(outFile, "w");
  const child = spawn(process.execPath, plan.argv, {
    cwd,
    env,
    detached: true,
    stdio: ["ignore", out, out],
    windowsHide: true
  });
  // The child has dup'd its own copy of the fd; close the parent's to avoid leaking it.
  fs.closeSync(out);
  child.unref();
  if (pidFile) {
    fs.writeFileSync(pidFile, String(child.pid), "utf8");
  }
  return child.pid;
}
