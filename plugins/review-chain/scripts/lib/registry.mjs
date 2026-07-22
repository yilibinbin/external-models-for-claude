// Registry: discover review-capable external-model plugins at runtime and map each
// to the flag dialect its companion understands. No manifest capability field exists in
// this marketplace, so discovery is by convention (see enumerateReviewPlugins).

import fs from "node:fs";
import path from "node:path";

import { runCommand } from "./process.mjs";

const MARKETPLACE = "external-models-for-claude";

// Per-companion adapter. Keyed by the companion script basename, which is the stable
// contract across plugins. The three shipped reviewers diverge in their flag surfaces:
//   - codex + gemini accept --scope/--base; antigravity does NOT (it always reviews the
//     full working+staged tree). Passing --scope/--base to antigravity makes it reject.
//   - codex tunes strength via --quality; gemini via --adversarial-lenses; antigravity
//     via --structured + --model-provider.
// A single logical intent (scope/base/focus) is translated into each dialect here.
const KNOWN_ADAPTERS = {
  "codex-companion.mjs": {
    supportsScope: true,
    supportsBase: true,
    jsonFlag: "--json"
  },
  "gemini-companion.mjs": {
    supportsScope: true,
    supportsBase: true,
    jsonFlag: "--json"
  },
  "antigravity-companion.mjs": {
    // Load-bearing: antigravity has no scope/base; it reviews the full dirty tree.
    supportsScope: false,
    supportsBase: false,
    jsonFlag: "--json"
  }
};

// Unknown/future plugins degrade conservatively: assume no scope/base until a capability
// probe proves the companion advertises them (probeCompanionCapabilities), so a
// parameterless-context plugin is never handed flags it rejects.
const DEFAULT_ADAPTER = {
  supportsScope: false,
  supportsBase: false,
  jsonFlag: "--json"
};

export function adapterFor(companionBasename) {
  return { ...(KNOWN_ADAPTERS[companionBasename] ?? DEFAULT_ADAPTER) };
}

// Normalize a plugin's install root across the schema variants `claude plugin list --json`
// is known to emit (codex handles the same set): installPath | path | root.
function normalizeInstallPath(entry) {
  for (const field of ["installPath", "path", "root"]) {
    if (typeof entry?.[field] === "string" && entry[field]) {
      return entry[field];
    }
  }
  return null;
}

// Read `claude plugin list --json` -> installed plugins under this marketplace. Accepts
// both a top-level array and a `{plugins:[...]}` envelope, and normalizes the root field,
// so the auto-join contract holds across the known CLI output shapes.
//
// Disabled plugins are excluded. A retired plugin survives in the version-pinned cache
// after it leaves the marketplace and is still listed with `enabled:false`; auto-joining
// it would put a stale reviewer back on the panel. Only an EXPLICIT false disqualifies —
// a CLI shape that omits `enabled` must still join, or the panel silently empties.
export function listInstalledPlugins(options = {}) {
  const runner = options.runner ?? defaultPluginListRunner;
  const raw = runner();
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  const entries = Array.isArray(parsed) ? parsed : Array.isArray(parsed?.plugins) ? parsed.plugins : [];
  return entries
    .filter((entry) => {
      const id = typeof entry?.id === "string" ? entry.id : "";
      return id.endsWith(`@${MARKETPLACE}`) && entry?.enabled !== false;
    })
    .map((entry) => ({ ...entry, installPath: normalizeInstallPath(entry) }));
}

function defaultPluginListRunner() {
  const result = runCommand("claude", ["plugin", "list", "--json"]);
  if (result.status !== 0) {
    return "[]";
  }
  return result.stdout ?? "[]";
}

// Locate the *-companion.mjs under an installed plugin's scripts dir.
export function findCompanion(installPath) {
  const scriptsDir = path.join(installPath, "scripts");
  let names;
  try {
    names = fs.readdirSync(scriptsDir);
  } catch {
    return null;
  }
  const match = names.find((name) => name.endsWith("-companion.mjs"));
  return match ? path.join(scriptsDir, match) : null;
}

// A plugin is review-capable iff it declares the adversarial-review capability by
// convention AND its companion advertises the subcommand. Both must hold (fail-loud:
// callers log skipped plugins).
export function isReviewCapable(installPath, options = {}) {
  const hasCommand = fs.existsSync(
    path.join(installPath, "commands", "adversarial-review.md")
  );
  const hasSkill = dirHasAdversarialSkill(path.join(installPath, "skills"));
  if (!hasCommand && !hasSkill) {
    return false;
  }
  const companion = findCompanion(installPath);
  if (!companion) {
    return false;
  }
  const probe = options.probe ?? probeCompanionAdvertisesAdversarialReview;
  return probe(companion);
}

function dirHasAdversarialSkill(skillsDir) {
  let entries;
  try {
    entries = fs.readdirSync(skillsDir);
  } catch {
    return false;
  }
  return entries.some((name) => {
    if (!name.includes("adversarial-review")) {
      return false;
    }
    return fs.existsSync(path.join(skillsDir, name, "SKILL.md"));
  });
}

function probeCompanionAdvertisesAdversarialReview(companionPath) {
  const result = runCommand(process.execPath, [companionPath, "--help"], { timeout: 10000 });
  const text = `${result.stdout ?? ""}\n${result.stderr ?? ""}`;
  return text.includes("adversarial-review");
}

// Enumerate the review-capable plugins with resolved companion + adapter dialect, in a
// stable order. Future plugins that ship the convention auto-join — no edit here.
export function enumerateReviewPlugins(options = {}) {
  const installed = listInstalledPlugins(options);
  const capable = [];
  const skipped = [];
  for (const entry of installed) {
    const installPath = entry.installPath;
    if (!installPath || !isReviewCapable(installPath, options)) {
      skipped.push(entry.id);
      continue;
    }
    const companion = findCompanion(installPath);
    capable.push({
      id: entry.id,
      name: entry.id.slice(0, entry.id.indexOf("@")),
      installPath,
      companion,
      adapter: adapterFor(path.basename(companion))
    });
  }
  return { capable, skipped };
}
