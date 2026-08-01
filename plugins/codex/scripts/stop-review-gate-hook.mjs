#!/usr/bin/env node

import fs from "node:fs";
import process from "node:process";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { getCodexAvailability } from "./lib/codex.mjs";
import { loadPromptTemplate, interpolateTemplate } from "./lib/prompts.mjs";
import { acquireResourceLease, capacityBlockedMessage } from "./lib/resource-governor.mjs";
import { getConfig, listJobs } from "./lib/state.mjs";
import { classifyStopGateResult } from "./lib/stop-gate-result.mjs";
import { sortJobsNewestFirst } from "./lib/job-control.mjs";
import { SESSION_ID_ENV } from "./lib/tracked-jobs.mjs";
import { sanitizeModelText } from "./lib/sanitize.mjs";
import { resolveWorkspaceRoot } from "./lib/workspace.mjs";

const STOP_REVIEW_TIMEOUT_MS = 8 * 60 * 1000;
const STOP_GATE_MUTEX_WAIT_MAX_MS = 60 * 1000;
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const ROOT_DIR = path.resolve(SCRIPT_DIR, "..");
const STOP_REVIEW_TASK_MARKER = "Run a stop-gate review of the previous Claude turn.";
let activeWorkspaceRoot = null;
let activeGateConfig = null;
let decisionEmitted = false;

function readHookInput() {
  const raw = fs.readFileSync(0, "utf8").trim();
  if (!raw) {
    return {};
  }
  try {
    return JSON.parse(raw);
  } catch (error) {
    // Re-throw without V8's quoted snippet. Its "Unexpected token" form embeds
    // the offending bytes verbatim, and those bytes are the Stop payload --
    // which carries last_assistant_message. The snippet cannot be redacted
    // reliably either: it is ~10 characters with no assignment structure, so it
    // matches neither the key/value rule nor a vendor token shape.
    //
    // The position is the whole diagnostic value here; the bytes are the payload.
    const position = /position (\d+)/.exec(error?.message ?? "")?.[1];
    throw new Error(
      position
        ? `hook stdin was not valid JSON (at position ${position})`
        : "hook stdin was not valid JSON"
    );
  }
}

// Redaction sits at the EMIT boundary, not only in classifyStopGateResult.
// handleHookException builds its own block reason and never calls the
// classifier, so a classifier-only fix leaves that degraded path open -- and it
// is a real carrier: readHookInput JSON.parse()s the Stop payload and V8's
// "Unexpected token" form quotes the offending bytes, while getConfig failures
// put absolute machine paths into the message.
//
// Bounding lives here too, for the same reason: every path crosses this seam.
const MAX_EMITTED_REASON_CHARS = 4000;
const REASON_TRUNCATION_SUFFIX = "... [truncated]";

function boundReason(reason) {
  const text = String(reason ?? "");
  return text.length > MAX_EMITTED_REASON_CHARS
    ? `${text.slice(0, MAX_EMITTED_REASON_CHARS - REASON_TRUNCATION_SUFFIX.length)}${REASON_TRUNCATION_SUFFIX}`
    : text;
}

function emitHookDecision(payload) {
  decisionEmitted = true;
  const safePayload =
    typeof payload?.reason === "string"
      ? { ...payload, reason: boundReason(sanitizeModelText(payload.reason)) }
      : payload;
  process.stdout.write(`${JSON.stringify(safePayload)}\n`);
}

function logNote(message) {
  if (!message) {
    return;
  }
  process.stderr.write(`${boundReason(sanitizeModelText(message))}\n`);
}

function filterJobsForCurrentSession(jobs, input = {}) {
  const sessionId = input.session_id || process.env[SESSION_ID_ENV] || null;
  if (!sessionId) {
    return jobs;
  }
  return jobs.filter((job) => job.sessionId === sessionId);
}

function buildStopReviewPrompt(input = {}) {
  const lastAssistantMessage = String(input.last_assistant_message ?? "").trim();
  const template = loadPromptTemplate(ROOT_DIR, "stop-review-gate");
  const claudeResponseBlock = lastAssistantMessage
    ? ["Previous Claude response:", lastAssistantMessage].join("\n")
    : "";
  return interpolateTemplate(template, {
    CLAUDE_RESPONSE_BLOCK: claudeResponseBlock
  });
}

function buildSetupNote(cwd) {
  const availability = getCodexAvailability(cwd);
  if (availability.available) {
    return null;
  }

  const detail = availability.detail ? ` ${availability.detail}.` : "";
  return `Codex is not set up for the review gate.${detail} Run /codex:setup.`;
}

export function stopGateLeaseEnv(env = process.env) {
  const raw = Number(env.CODEX_FOR_CLAUDE_MUTEX_WAIT_MS || 30000);
  const waitMs = Number.isFinite(raw) && raw > 0 ? Math.min(raw, STOP_GATE_MUTEX_WAIT_MAX_MS) : 30000;
  return { ...env, CODEX_FOR_CLAUDE_MUTEX_WAIT_MS: String(waitMs) };
}

export function parseStopReviewOutput(text) {
  const MAX_STOP_BLOCK_REASON_CHARS = 4000;
  const fullText = String(text || "").trim();
  const firstLine = fullText
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean) || "";
  const match = /^(ALLOW|BLOCK):\s*(.*)$/i.exec(firstLine);
  if (!match) {
    return { ok: false, kind: "invalid-output", reason: "Codex stop review did not return ALLOW: or BLOCK:." };
  }
  const verdict = match[1].toUpperCase();
  const blockDetail = verdict === "BLOCK" ? fullText.replace(/^\s*BLOCK:\s*/i, "").trim() : "";
  // Redact BEFORE slicing. Cutting a recognized token turns it into an
  // unrecognized fragment: a 39-char Google API key straddling the cutoff
  // emitted 38 characters with no marker, leaving one character to enumerate.
  // Same ordering error as truncating stderr before redacting it.
  const reason = sanitizeModelText(blockDetail || match[2] || fullText || verdict);
  const suffix = "\n[truncated]";
  const boundedReason = reason.length > MAX_STOP_BLOCK_REASON_CHARS
    ? `${reason.slice(0, MAX_STOP_BLOCK_REASON_CHARS - suffix.length)}${suffix}`
    : reason;
  return {
    ok: true,
    verdict,
    reason: boundedReason
  };
}

export function classifyStopTaskProcessResult(result) {
  if (result.error?.code === "ETIMEDOUT") {
    return { ok: false, kind: "timeout", reason: "Codex stop review timed out." };
  }
  const detail = String(result.stderr || result.error?.message || result.stdout || "").trim();
  const processFailed = result.status !== 0 || Boolean(result.error);
  const processFailure = () => {
    if (/auth|login|unauthenticated/i.test(detail)) {
      return { ok: false, kind: "auth", reason: "Codex is not authenticated." };
    }
    return { ok: false, kind: "status", reason: detail || `Codex exited with status ${result.status}.` };
  };
  let payload;
  try {
    payload = JSON.parse(result.stdout || "{}");
  } catch {
    if (!processFailed) {
      return { ok: false, kind: "invalid-json", reason: "Codex stop review returned invalid JSON." };
    }
    return processFailure();
  }
  // A turn that completed WITHOUT a final answer is not an authoritative
  // verdict: `turn/completed` can land with status 0 while the captured text is
  // intermediate commentary, and an ALLOW parsed from commentary would open a
  // fail-closed gate. Treat it as a process failure.
  if (payload && payload.finalAnswerSeen === false) {
    return { ok: false, kind: "no-final-answer", reason: "Codex stop review did not produce a final answer." };
  }
  const parsed = parseStopReviewOutput(payload?.rawOutput || "");
  if (parsed.ok) {
    if (parsed.verdict === "BLOCK") {
      return parsed;
    }
    if (processFailed) {
      return processFailure();
    }
    return parsed;
  }
  if (processFailed) {
    return processFailure();
  }
  return parsed;
}

function runStopReview(cwd, input = {}, stopGateLease, leaseEnv) {
  const scriptPath = path.join(SCRIPT_DIR, "codex-companion.mjs");
  const prompt = buildStopReviewPrompt(input);
  const effectiveLeaseEnv = leaseEnv ?? stopGateLeaseEnv(process.env);
  const hasParentStopGateLease = Boolean(stopGateLease?.id);
  const childEnv = {
    ...effectiveLeaseEnv,
    CODEX_FOR_CLAUDE_MUTEX_WAIT_MS: effectiveLeaseEnv.CODEX_FOR_CLAUDE_MUTEX_WAIT_MS,
    CODEX_FOR_CLAUDE_SKIP_STATE_PRUNE: "1",
    CODEX_FOR_CLAUDE_FILE_LOCK_WAIT_MS: "35000",
    CODEX_FOR_CLAUDE_DISABLE_HEARTBEAT: "1",
    CODEX_FOR_CLAUDE_DISABLE_PROGRESS_UPDATES: "1",
    ...(hasParentStopGateLease ? {
      CODEX_FOR_CLAUDE_STOP_GATE_CHILD: "1",
      CODEX_FOR_CLAUDE_PARENT_STOP_GATE_LEASE_ID: stopGateLease.id,
      CODEX_FOR_CLAUDE_PARENT_STOP_GATE_PID: String(process.pid)
    } : {}),
    ...(input.session_id ? { [SESSION_ID_ENV]: input.session_id } : {})
  };
  const result = spawnSync(process.execPath, [scriptPath, "task", "--json", "--", prompt], {
    cwd,
    env: childEnv,
    encoding: "utf8",
    // Default 1 MiB is too small for verbose --json review output; an ENOBUFS
    // truncation would look like a tool failure and (fail-closed) block Stop.
    maxBuffer: 16 * 1024 * 1024,
    timeout: STOP_REVIEW_TIMEOUT_MS
  });

  return classifyStopTaskProcessResult(result);
}

function withStopGateLease(cwd, callback) {
  if (!activeGateConfig) {
    throw new Error("Stop gate config must be loaded before acquiring the stop-gate lease.");
  }
  const leaseEnv = stopGateLeaseEnv(process.env);
  const lease = acquireResourceLease("stop-gate", { env: leaseEnv, command: "stop-review-gate" });
  if (!lease.ok) {
    const result = { ok: false, kind: "capacity", reason: capacityBlockedMessage(lease) };
    const decision = classifyStopGateResult(result, { failOpen: Boolean(activeGateConfig?.stopReviewGateFailOpen) });
    if (decision.decision === "block") {
      emitHookDecision({ decision: "block", reason: decision.reason });
    } else {
      logNote(`[codex review-gate] ${decision.reason}`);
    }
    return;
  }
  try {
    return callback(lease.lease ?? lease, leaseEnv);
  } finally {
    lease.release?.();
  }
}

function main() {
  if (String(process.env.CODEX_FOR_CLAUDE_REVIEW_GATE || "").toLowerCase() === "off") {
    return;
  }
  if (process.env.NODE_ENV === "test" && process.env.CODEX_FOR_CLAUDE_TEST_HOOK_THROW === "1") {
    throw new Error("test hook crash");
  }
  const input = readHookInput();
  // The host sets stop_hook_active when Stop fires because a hook already
  // blocked. Running another full review then costs a second eight-minute
  // Codex turn per iteration -- and the new fail-closed path for a turn with no
  // final answer makes that loop reachable, since it blocks without ever
  // reaching a verdict. Allow the Stop through; the gate already had its say.
  if (input.stop_hook_active) {
    return;
  }
  const cwd = input.cwd || process.env.CLAUDE_PROJECT_DIR || process.cwd();
  const workspaceRoot = resolveWorkspaceRoot(cwd);
  const config = getConfig(workspaceRoot);

  const jobs = sortJobsNewestFirst(filterJobsForCurrentSession(listJobs(workspaceRoot), input));
  const runningJob = jobs.find((job) => job.status === "queued" || job.status === "running");
  const runningTaskNote = runningJob
    ? `Codex task ${runningJob.id} is still running. Check /codex:status and use /codex:cancel ${runningJob.id} if you want to stop it before ending the session.`
    : null;

  if (!config.stopReviewGate) {
    logNote(runningTaskNote);
    return;
  }

  activeWorkspaceRoot = workspaceRoot;
  activeGateConfig = config;
  const setupNote = buildSetupNote(cwd);
  if (setupNote) {
    const decision = classifyStopGateResult({ ok: false, kind: "setup", reason: setupNote }, {
      failOpen: Boolean(config.stopReviewGateFailOpen)
    });
    if (decision.decision === "block") {
      emitHookDecision({ decision: "block", reason: runningTaskNote ? `${runningTaskNote} ${decision.reason}` : decision.reason });
    } else {
      logNote(runningTaskNote ? `${runningTaskNote} [codex review-gate] ${decision.reason}` : `[codex review-gate] ${decision.reason}`);
    }
    return;
  }

  return withStopGateLease(workspaceRoot, (stopGateLease, leaseEnv) => {
    const review = runStopReview(cwd, input, stopGateLease, leaseEnv);
    const decision = classifyStopGateResult(review, { failOpen: Boolean(config.stopReviewGateFailOpen) });
    if (decision.decision === "block") {
      emitHookDecision({ decision: "block", reason: runningTaskNote ? `${runningTaskNote} ${decision.reason}` : decision.reason });
      return;
    }
    if (decision.toolFailure) {
      logNote(runningTaskNote ? `${runningTaskNote} [codex review-gate] ${decision.reason}` : `[codex review-gate] ${decision.reason}`);
      return;
    }
    logNote(runningTaskNote);
  });
}

function handleHookException(error) {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`${boundReason(sanitizeModelText(`[codex review-gate] failed: ${message}`))}\n`);
  let config = activeGateConfig;
  if (!config) {
    try {
      // Honor the intended workspace even when stdin was unparseable (so
      // activeWorkspaceRoot was never set): match main()'s resolution order
      // — CLAUDE_PROJECT_DIR before process.cwd() — so a malformed Stop payload
      // still fails closed against the CORRECT workspace's gate config.
      config = getConfig(
        activeWorkspaceRoot
          ?? resolveWorkspaceRoot(process.env.CLAUDE_PROJECT_DIR || process.cwd())
      );
    } catch (configError) {
      const configMessage = configError instanceof Error ? configError.message : String(configError);
      process.stderr.write(`${boundReason(sanitizeModelText(`[codex review-gate] could not determine gate config; allowing Stop: ${configMessage}`))}\n`);
      return;
    }
  }
  if (!decisionEmitted && config.stopReviewGate && !Boolean(config.stopReviewGateFailOpen)) {
    emitHookDecision({ decision: "block", reason: `Codex review-gate failed: ${message}` });
  }
}

function isDirectHookEntrypoint(argvPath = process.argv[1]) {
  if (!argvPath) return false;
  try {
    return fs.realpathSync(fileURLToPath(import.meta.url)) === fs.realpathSync(argvPath);
  } catch {
    return fileURLToPath(import.meta.url) === path.resolve(argvPath);
  }
}

if (isDirectHookEntrypoint()) {
  try {
    main();
  } catch (error) {
    handleHookException(error);
  }
}
