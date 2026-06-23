#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

if (String(process.env.ANTIGRAVITY_FOR_CLAUDE_REVIEW_GATE ?? "").toLowerCase() === "off") {
  process.exit(0);
}

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const RUNTIME = path.resolve(SCRIPT_DIR, "..", "scripts", "antigravity-companion.mjs");
const WRAPPER_TIMEOUT_MS = 870 * 1000;

// Best-effort, NON-BLOCKING read of the host hook payload so we can honour the
// Claude Code stop_hook_active loop-guard and cwd. We must never block here: an
// open host pipe without EOF would bypass the wrapper timeout. A non-blocking
// read returns only data already buffered; if stdin is not ready we skip it.
// Parsed values are passed via env vars rather than forwarding an open pipe.
const childEnv = { ...process.env };
try {
  if (!process.stdin.isTTY) {
    let rawInput = "";
    const chunk = Buffer.alloc(64 * 1024);
    try {
      const fd0 = fs.openSync("/dev/stdin", fs.constants.O_RDONLY | fs.constants.O_NONBLOCK);
      try {
        let bytes;
        do {
          bytes = fs.readSync(fd0, chunk, 0, chunk.length, null);
          if (bytes > 0) {
            rawInput += chunk.toString("utf8", 0, bytes);
          }
        } while (bytes === chunk.length);
      } finally {
        fs.closeSync(fd0);
      }
    } catch {
      // EAGAIN (no data ready) or no /dev/stdin: skip; the gate still runs.
    }
    rawInput = rawInput.trim();
    if (rawInput) {
      const payload = JSON.parse(rawInput);
      if (payload && payload.stop_hook_active) {
        childEnv.ANTIGRAVITY_FOR_CLAUDE_STOP_HOOK_ACTIVE = "1";
      }
      if (payload && typeof payload.cwd === "string" && payload.cwd) {
        childEnv.ANTIGRAVITY_FOR_CLAUDE_HOOK_CWD = payload.cwd;
      }
    }
  }
} catch (error) {
  // A garbled/empty payload must not break the gate; fall through with no hints.
  process.stderr.write(`[antigravity-for-claude review-gate] could not parse hook input; continuing: ${error.message || String(error)}\n`);
}

try {
  const result = spawnSync(process.execPath, [RUNTIME, "review-gate"], {
    cwd: process.cwd(),
    env: childEnv,
    encoding: "utf8",
    maxBuffer: 20 * 1024 * 1024,
    timeout: WRAPPER_TIMEOUT_MS
  });

  if (result.stdout) {
    process.stdout.write(result.stdout);
  }
  if (result.stderr) {
    process.stderr.write(result.stderr);
  }
  if (result.error) {
    process.stderr.write(`[antigravity-for-claude review-gate] wrapper failed; allowing stop: ${result.error.message}\n`);
  }
} catch (error) {
  process.stderr.write(`[antigravity-for-claude review-gate] wrapper error; allowing stop: ${error.message || String(error)}\n`);
}

process.exitCode = 0;
