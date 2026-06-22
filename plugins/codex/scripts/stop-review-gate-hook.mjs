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
  return JSON.parse(raw);
}

function emitHookDecision(payload) {
  decisionEmitted = true;
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function logNote(message) {
  if (!message) {
    return;
  }
  process.stderr.write(`${message}\n`);
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
  const reason = blockDetail || match[2] || fullText || verdict;
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
  const detail = String(result.stderr || result.stdout || result.error?.message || "").trim();
  let payload;
  try {
    payload = JSON.parse(result.stdout || "{}");
  } catch {
    if (result.status === 0) {
      return { ok: false, kind: "invalid-json", reason: "Codex stop review returned invalid JSON." };
    }
    if (/auth|login|unauthenticated/i.test(detail)) {
      return { ok: false, kind: "auth", reason: "Codex is not authenticated." };
    }
    return { ok: false, kind: "status", reason: detail || `Codex exited with status ${result.status}.` };
  }
  const parsed = parseStopReviewOutput(payload?.rawOutput || "");
  if (parsed.ok) {
    return parsed;
  }
  if (result.status !== 0) {
    if (/auth|login|unauthenticated/i.test(detail)) {
      return { ok: false, kind: "auth", reason: "Codex is not authenticated." };
    }
    return { ok: false, kind: "status", reason: detail || `Codex exited with status ${result.status}.` };
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
    logNote(setupNote);
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
  process.stderr.write(`[codex review-gate] failed: ${message}\n`);
  let config = activeGateConfig;
  if (!config) {
    try {
      config = getConfig(activeWorkspaceRoot ?? resolveWorkspaceRoot(process.cwd()));
    } catch (configError) {
      const configMessage = configError instanceof Error ? configError.message : String(configError);
      process.stderr.write(`[codex review-gate] could not determine gate config; allowing Stop: ${configMessage}\n`);
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
