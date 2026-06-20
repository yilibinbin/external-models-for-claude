import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { resolveInstalledPluginRoot } from "./install-consistency.mjs";
import { ensureStateDir, resolveStateDir } from "./state.mjs";

function firstLine(text) {
  return String(text ?? "")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean) ?? "";
}

export function commandVersion(command, args = ["--version"], env = process.env) {
  const result = spawnSync(command, args, {
    env,
    encoding: "utf8",
    timeout: 5000,
    maxBuffer: 1024 * 1024,
    windowsHide: true
  });

  if (result.error) {
    return {
      ok: false,
      command,
      reason: result.error.code ?? "command failed"
    };
  }

  if (result.status !== 0) {
    return {
      ok: false,
      command,
      reason: `exit ${result.status}`
    };
  }

  const output = firstLine(result.stdout) || firstLine(result.stderr);
  return {
    ok: true,
    command,
    version: output || null
  };
}

export function stateDirStatus(cwd) {
  let basename = "unknown";
  try {
    const stateDir = resolveStateDir(cwd);
    basename = path.basename(stateDir);
    ensureStateDir(cwd);
    const probe = path.join(stateDir, `.doctor-probe-${process.pid}-${Date.now()}`);
    fs.writeFileSync(probe, "ok\n", "utf8");
    fs.unlinkSync(probe);
    return {
      available: true,
      basename,
      writable: true
    };
  } catch (error) {
    return {
      available: false,
      basename,
      writable: false,
      reason: error?.code ? String(error.code) : "state directory unavailable"
    };
  }
}

function installedPluginCheck(env) {
  const result = resolveInstalledPluginRoot(env);
  if (!result.ok) {
    return {
      ok: false,
      advisory: true,
      reason: result.reason
    };
  }

  return {
    ok: true,
    advisory: true,
    basename: path.basename(result.installPath)
  };
}

export function doctorReport(cwd = process.cwd(), env = process.env) {
  const checks = {
    node: commandVersion("node", ["--version"], env),
    codexExecutable: commandVersion("codex", ["--version"], env),
    claudeExecutable: commandVersion("claude", ["--version"], env),
    installedPlugin: installedPluginCheck(env)
  };
  const stateDir = stateDirStatus(cwd);
  const blockingFailures = Object.entries({
    node: checks.node.ok,
    codexExecutable: checks.codexExecutable.ok,
    claudeExecutable: checks.claudeExecutable.ok,
    stateDir: stateDir.available && stateDir.writable
  })
    .filter(([, ok]) => !ok)
    .map(([name]) => name);
  const advisoryFailures = checks.installedPlugin.ok ? [] : ["installedPlugin"];
  const ready = blockingFailures.length === 0;

  return {
    ok: true,
    ready,
    checks,
    blockingFailures,
    advisoryFailures,
    installedPluginRequired: false,
    stateDir,
    summary: ready
      ? "Codex doctor found all blocking local prerequisites."
      : `Codex doctor found ${blockingFailures.length} blocking local prerequisite failure(s).`
  };
}
