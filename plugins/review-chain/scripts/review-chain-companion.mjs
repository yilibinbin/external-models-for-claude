#!/usr/bin/env node
// review-chain companion — the mechanical layer of the shared serial adversarial-review
// chain. It enumerates review-capable plugins, builds the shared diff, dispatches each
// reviewer in its own flag dialect, and accumulates a findings ledger. The JUDGMENT
// (brokering findings, the rebuttal loop, arbitration) lives in the skill and is run by
// the main-thread Claude — this script only does deterministic work.

import fs from "node:fs";
import path from "node:path";

import { resolveReviewTarget, collectReviewContext } from "./lib/git.mjs";
import { enumerateReviewPlugins, adapterFor } from "./lib/registry.mjs";
import { initLedger, appendStage, readLedger } from "./lib/ledger.mjs";
import { buildDispatchPlan, runDispatch, defaultOutFile } from "./lib/dispatch.mjs";

function printUsage() {
  process.stdout.write(
    [
      "Usage:",
      "  node review-chain-companion.mjs enumerate [--json]",
      "  node review-chain-companion.mjs build-diff [--cwd <dir>] [--scope auto|working-tree|branch] [--base <ref>] [--json]",
      "  node review-chain-companion.mjs ledger init --out <file> [--target <label>]",
      "  node review-chain-companion.mjs ledger show --out <file> [--json]",
      "  node review-chain-companion.mjs dispatch --plugin <name> [--scope ...] [--base <ref>] [--quality <q>] [--dry-run] [--json] [--out-file <f>] [--pid-file <f>] [-- focus ...]",
      "  node review-chain-companion.mjs wait --pid <pid> [--pid-file <f>] [--timeout-seconds <n>]",
      ""
    ].join("\n")
  );
}

// Minimal, self-contained arg parser: value flags take the next token, boolean flags are
// presence-only. Positionals are collected. Never interpolates prose into a shell.
function parse(argv, { value = [], boolean = [] } = {}) {
  const valueSet = new Set(value);
  const boolSet = new Set(boolean);
  const opts = {};
  const positionals = [];
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === "--") {
      positionals.push(...argv.slice(i + 1));
      break;
    }
    if (token.startsWith("--")) {
      const [key, inline] = token.slice(2).split("=", 2);
      if (boolSet.has(key)) {
        opts[key] = inline === undefined ? true : inline !== "false";
      } else if (valueSet.has(key)) {
        const next = inline ?? argv[i + 1];
        if (next === undefined) {
          throw new Error(`Missing value for --${key}`);
        }
        opts[key] = next;
        if (inline === undefined) {
          i += 1;
        }
      } else {
        throw new Error(`Unknown flag: --${key}`);
      }
    } else {
      positionals.push(token);
    }
  }
  return { opts, positionals };
}

function cmdEnumerate(argv) {
  const { opts } = parse(argv, { boolean: ["json"] });
  const result = enumerateReviewPlugins();
  if (opts.json) {
    process.stdout.write(JSON.stringify(result, null, 2) + "\n");
    return 0;
  }
  process.stdout.write(`Review-capable plugins (${result.capable.length}):\n`);
  for (const p of result.capable) {
    const scope = p.adapter.supportsScope ? "scope+base" : "no-scope";
    process.stdout.write(`  - ${p.name} [${scope}] ${p.companion}\n`);
  }
  if (result.skipped.length) {
    process.stdout.write(`Skipped (not review-capable): ${result.skipped.join(", ")}\n`);
  }
  return 0;
}

function cmdBuildDiff(argv) {
  const { opts } = parse(argv, {
    value: ["cwd", "scope", "base"],
    boolean: ["json"]
  });
  const cwd = opts.cwd ? path.resolve(opts.cwd) : process.cwd();
  const target = resolveReviewTarget(cwd, { scope: opts.scope, base: opts.base });
  const context = collectReviewContext(cwd, target);
  if (opts.json) {
    process.stdout.write(JSON.stringify(context, null, 2) + "\n");
    return 0;
  }
  process.stdout.write(`${context.target.label} — ${context.fileCount} file(s)\n`);
  return 0;
}

function cmdLedger(argv) {
  const [sub, ...rest] = argv;
  if (sub === "init") {
    const { opts } = parse(rest, { value: ["out", "target", "mode"] });
    if (!opts.out) {
      throw new Error("ledger init requires --out <file>");
    }
    initLedger(opts.out, { target: opts.target ?? null, mode: opts.mode ?? null });
    process.stdout.write(`ledger initialized: ${opts.out}\n`);
    return 0;
  }
  if (sub === "show") {
    const { opts } = parse(rest, { value: ["out"], boolean: ["json"] });
    if (!opts.out) {
      throw new Error("ledger show requires --out <file>");
    }
    const ledger = readLedger(opts.out);
    if (opts.json) {
      process.stdout.write(JSON.stringify(ledger, null, 2) + "\n");
      return 0;
    }
    process.stdout.write(`target: ${ledger.target}\nstages: ${ledger.stages.length}\n`);
    for (const stage of ledger.stages) {
      process.stdout.write(`  - ${stage.reviewer}: ${stage.normalizedGate} (${stage.rawVerdict})\n`);
    }
    return 0;
  }
  if (sub === "append") {
    const { opts } = parse(rest, { value: ["out", "reviewer", "verdict", "raw-file"] });
    if (!opts.out || !opts.reviewer) {
      throw new Error("ledger append requires --out and --reviewer");
    }
    // rawOutput is read from a file (never a shell arg) to keep it byte-exact and prose-safe.
    let rawOutput = "";
    if (opts["raw-file"]) {
      rawOutput = fs.readFileSync(opts["raw-file"], "utf8");
    }
    appendStage(opts.out, {
      reviewer: opts.reviewer,
      rawVerdict: opts.verdict ?? null,
      rawOutput
    });
    process.stdout.write(`appended stage: ${opts.reviewer}\n`);
    return 0;
  }
  throw new Error(`Unknown ledger subcommand: ${sub ?? "(none)"}`);
}

// Resolve a plugin's companion path + adapter, either from an explicit --companion
// override (tests / advanced use) or by matching the live enumeration.
// The canonical plugin key is the name before `@` in an id, or a bare name as-is. Codex
// behavior (env-unset, --quality) keys off this canonical name, never off raw caller input.
function canonicalName(pluginRef) {
  const at = pluginRef.indexOf("@");
  return at === -1 ? pluginRef : pluginRef.slice(0, at);
}

function resolvePluginTarget(pluginRef, companionOverride) {
  if (companionOverride) {
    return {
      name: canonicalName(pluginRef),
      companion: companionOverride,
      adapter: adapterFor(path.basename(companionOverride))
    };
  }
  const { capable } = enumerateReviewPlugins();
  const match = capable.find((p) => p.name === pluginRef || p.id === pluginRef);
  if (!match) {
    throw new Error(`No review-capable plugin named "${pluginRef}" is installed.`);
  }
  return { name: match.name, companion: match.companion, adapter: match.adapter };
}

function cmdDispatch(argv) {
  const { opts, positionals } = parse(argv, {
    value: ["plugin", "companion", "scope", "base", "quality", "cwd", "out-file", "pid-file"],
    boolean: ["dry-run", "json"]
  });
  if (!opts.plugin) {
    throw new Error("dispatch requires --plugin <name>");
  }
  const { name, companion, adapter } = resolvePluginTarget(opts.plugin, opts.companion);
  const plan = buildDispatchPlan({
    plugin: opts.plugin,
    name,
    companion,
    adapter,
    scope: opts.scope,
    base: opts.base,
    quality: opts.quality,
    focus: positionals
  });
  // Artifacts default OUTSIDE the target repo so a full-tree reviewer never inspects them.
  const outFile = opts["out-file"] ?? defaultOutFile(name);

  if (opts["dry-run"]) {
    const view = { ...plan, defaultOutFile: outFile };
    if (opts.json) {
      process.stdout.write(JSON.stringify(view, null, 2) + "\n");
    } else {
      process.stdout.write(`${plan.plugin}: ${plan.argv.join(" ")}\n`);
    }
    return 0;
  }

  const cwd = opts.cwd ? path.resolve(opts.cwd) : process.cwd();
  const pidFile = opts["pid-file"] ?? null;
  const pid = runDispatch(plan, { cwd, outFile, pidFile });
  process.stdout.write(JSON.stringify({ plugin: name, pid, outFile, pidFile }) + "\n");
  return 0;
}

// Block until a dispatched reviewer PID exits. Gives the broker a node:-prefixed way to
// wait (the command wrapper only permits Bash(node:*)/Bash(git:*), so `wait`/`sleep`
// shell builtins are unavailable). Polls liveness with signal 0.
async function cmdWait(argv) {
  const { opts } = parse(argv, { value: ["pid", "pid-file", "timeout-seconds"] });
  let pid = opts.pid ? Number(opts.pid) : null;
  if (!pid && opts["pid-file"]) {
    pid = Number(fs.readFileSync(opts["pid-file"], "utf8").trim());
  }
  if (!pid || Number.isNaN(pid)) {
    throw new Error("wait requires --pid <pid> or --pid-file <file>");
  }
  const deadline = opts["timeout-seconds"]
    ? Date.now() + Number(opts["timeout-seconds"]) * 1000
    : null;
  const alive = (p) => {
    try {
      process.kill(p, 0);
      return true;
    } catch {
      return false;
    }
  };
  while (alive(pid)) {
    if (deadline && Date.now() > deadline) {
      process.stdout.write(JSON.stringify({ pid, exited: false, timedOut: true }) + "\n");
      return 1;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  process.stdout.write(JSON.stringify({ pid, exited: true }) + "\n");
  return 0;
}

async function main() {
  const [command, ...argv] = process.argv.slice(2);
  if (!command || command === "--help" || command === "-h") {
    printUsage();
    return command ? 0 : 1;
  }
  switch (command) {
    case "enumerate":
      return cmdEnumerate(argv);
    case "build-diff":
      return cmdBuildDiff(argv);
    case "ledger":
      return cmdLedger(argv);
    case "dispatch":
      return cmdDispatch(argv);
    case "wait":
      return cmdWait(argv);
    default:
      process.stderr.write(`Unknown command: ${command}\n`);
      printUsage();
      return 1;
  }
}

try {
  process.exit(await main());
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exit(1);
}
