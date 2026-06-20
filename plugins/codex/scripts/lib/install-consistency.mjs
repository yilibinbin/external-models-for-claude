import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const PLUGIN_ID = "codex@external-models-for-claude";
const MAX_PLUGIN_LIST_BUFFER = 2 * 1024 * 1024;

function supportedRootField(entry) {
  for (const field of ["installPath", "path", "root"]) {
    const value = entry?.[field];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return "";
}

export function installedCodexEntry(listJson) {
  let data = listJson;
  if (typeof data === "string") {
    try {
      data = JSON.parse(data);
    } catch {
      return null;
    }
  }

  const plugins = Array.isArray(data) ? data : data?.plugins;
  if (!Array.isArray(plugins)) {
    return null;
  }

  const entry = plugins.find((item) => item?.name === "codex" || item?.id === PLUGIN_ID);
  if (!entry) {
    return null;
  }

  return {
    ...entry,
    installPath: supportedRootField(entry)
  };
}

export function resolveInstalledPluginRoot(env = process.env) {
  const result = spawnSync("claude", ["plugin", "list", "--json"], {
    env,
    encoding: "utf8",
    timeout: 5000,
    maxBuffer: MAX_PLUGIN_LIST_BUFFER,
    windowsHide: true
  });

  if (result.error) {
    return { ok: false, reason: result.error.code ?? "claude plugin list failed" };
  }
  if (result.status !== 0) {
    return { ok: false, reason: "claude plugin list failed" };
  }

  const entry = installedCodexEntry(result.stdout);
  if (!entry) {
    return { ok: false, reason: "codex plugin is not installed" };
  }
  if (!entry.installPath) {
    return { ok: false, reason: "installed codex plugin entry has no supported root field" };
  }

  try {
    const companionPath = path.join(entry.installPath, "scripts", "codex-companion.mjs");
    if (!fs.existsSync(companionPath)) {
      return { ok: false, reason: "installed codex plugin companion script is missing" };
    }
  } catch {
    return { ok: false, reason: "installed codex plugin root could not be checked" };
  }

  return { ok: true, installPath: entry.installPath };
}
