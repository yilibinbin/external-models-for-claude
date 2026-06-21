import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import {
  CLAUDE_CODE_NPM_VERSION,
  CODEX_CLI_NPM_VERSION,
  releaseHostContractsVerified,
  renderWorkflow,
  validateWorkflow
} from "./github-actions.mjs";
import { hasMachinePath, MACHINE_PATH_PATTERN_SOURCE } from "./path-hygiene.mjs";

export const MARKETPLACE_VERSION = "0.2.0";
export const CODEX_VERSION = "1.1.0-fh.1";
export const MARKETPLACE_CODEX_AUTHOR = {
  name: "OpenAI",
  url: "https://github.com/openai/codex-plugin-cc"
};
export const PLUGIN_CODEX_AUTHOR = { name: "OpenAI" };
export const EXPECTED_COMMANDS = [
  "adversarial-review.md",
  "cancel.md",
  "doctor.md",
  "github-actions.md",
  "rescue.md",
  "result.md",
  "review.md",
  "setup.md",
  "status.md"
];
export const PREVIEW_COMMANDS = new Set(["github-actions.md"]);
export const READY_COMMANDS = EXPECTED_COMMANDS.filter((name) => !PREVIEW_COMMANDS.has(name));
export const DEFAULT_EXPECT_MARKETPLACE_ENTRY_VERSION = false;

const CODEX_PLUGIN_DIR = path.join("plugins", "codex");
const INSTALL_COMMAND =
  "claude plugin marketplace add yilibinbin/external-models-for-claude --scope user";
const INSTALL_TARGET = "codex@external-models-for-claude";
const TEXT_EXTENSIONS = new Set([".md", ".mdx", ".mjs", ".ts", ".txt", ".json", ".yaml", ".yml"]);
const TEXT_FILENAMES = new Set(["LICENSE", "NOTICE"]);
const EXCLUDED_SHIPPED_TEXT_DIRS = new Set([
  ".cache",
  ".git",
  ".pytest_cache",
  "__pycache__",
  "build",
  "coverage",
  "dist",
  "node_modules"
]);
const EXPECTED_HOOK_COMMANDS = {
  SessionStart: {
    command: 'node "${CLAUDE_PLUGIN_ROOT}/scripts/session-lifecycle-hook.mjs" SessionStart',
    minTimeout: 1,
    maxTimeout: 30
  },
  SessionEnd: {
    command: 'node "${CLAUDE_PLUGIN_ROOT}/scripts/session-lifecycle-hook.mjs" SessionEnd',
    minTimeout: 1,
    maxTimeout: 30
  },
  Stop: {
    command: 'node "${CLAUDE_PLUGIN_ROOT}/scripts/stop-review-gate-hook.mjs"',
    minTimeout: 60,
    maxTimeout: 1800
  }
};

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function readTextIfExists(filePath) {
  if (!fs.existsSync(filePath)) {
    return null;
  }
  return fs.readFileSync(filePath, "utf8");
}

function relativePath(root, filePath) {
  return path.relative(root, filePath).split(path.sep).join("/");
}

function arraysEqual(left, right) {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

function sameJson(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function check(name, ok, detail = null) {
  return { name, ok: Boolean(ok), detail };
}

function probeCodexStdinLogin(apiKey) {
  if (!apiKey) {
    return {
      ok: false,
      detail: "OPENAI_API_KEY is required to verify codex login --with-api-key stdin contract"
    };
  }
  const probeHome = fs.mkdtempSync(path.join(os.tmpdir(), "codex-release-auth-"));
  try {
    const probe = spawnSync("codex", ["login", "--with-api-key"], {
      input: `${apiKey}\n`,
      encoding: "utf8",
      timeout: 15000,
      env: {
        ...process.env,
        HOME: probeHome,
        XDG_CONFIG_HOME: path.join(probeHome, ".config"),
        CODEX_HOME: path.join(probeHome, ".codex")
      }
    });
    if (probe.error) {
      return { ok: false, detail: `stdin codex login probe failed: ${probe.error.message}` };
    }
    if (probe.status !== 0) {
      return {
        ok: false,
        detail: `stdin codex login --with-api-key probe failed with status ${probe.status}`
      };
    }
    return { ok: true, detail: "verified local codex login --with-api-key stdin contract" };
  } finally {
    fs.rmSync(probeHome, { recursive: true, force: true });
  }
}

function isTextFile(filePath) {
  return TEXT_EXTENSIONS.has(path.extname(filePath)) || TEXT_FILENAMES.has(path.basename(filePath));
}

function isExcludedShippedTextDir(dirName) {
  if (dirName === ".claude-plugin") {
    return false;
  }
  return (
    EXCLUDED_SHIPPED_TEXT_DIRS.has(dirName) ||
    dirName.startsWith(".") ||
    dirName.toLowerCase().includes("cache")
  );
}

function listFiles(rootPath, options = {}) {
  if (!fs.existsSync(rootPath)) {
    return [];
  }
  const stat = fs.lstatSync(rootPath);
  if (stat.isSymbolicLink()) {
    return [];
  }
  if (stat.isFile()) {
    return isTextFile(rootPath) ? [rootPath] : [];
  }
  if (!stat.isDirectory()) {
    return [];
  }
  return fs
    .readdirSync(rootPath, { withFileTypes: true })
    .filter((entry) => !(entry.isDirectory() && options.excludeDir?.(entry.name)))
    .flatMap((entry) => listFiles(path.join(rootPath, entry.name), options));
}

function shippedTextFiles(root) {
  const rootFiles = [
    "README.md",
    path.join(".claude-plugin", "marketplace.json"),
    path.join("docs", "README.en.md"),
    path.join("docs", "README.zh-CN.md"),
    "THIRD_PARTY_NOTICES.md"
  ];
  const pluginRoot = path.join(CODEX_PLUGIN_DIR);

  return [
    ...rootFiles.flatMap((entry) => listFiles(path.join(root, entry))),
    ...listFiles(path.join(root, pluginRoot), { excludeDir: isExcludedShippedTextDir })
  ]
    .sort((left, right) => relativePath(root, left).localeCompare(relativePath(root, right)));
}

export function findRepoRoot(start = process.cwd()) {
  let current = path.resolve(start);
  if (fs.existsSync(current) && fs.statSync(current).isFile()) {
    current = path.dirname(current);
  }

  while (true) {
    if (fs.existsSync(path.join(current, ".claude-plugin", "marketplace.json"))) {
      return current;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      throw new Error(
        `Could not find marketplace repository root from ${path.resolve(start)}; expected .claude-plugin/marketplace.json.`
      );
    }
    current = parent;
  }
}

export function versionAxisConfirmation(start = process.cwd()) {
  const root = findRepoRoot(start);
  const evidencePath = path.join(root, CODEX_PLUGIN_DIR, "VERSION_AXIS_CONFIRMATION.md");
  const text = readTextIfExists(evidencePath);
  if (text == null) {
    return {
      exists: false,
      marketplaceEntryVersionSupported: false,
      marketplaceEntryVersionUnsupported: false,
      validatorUnavailable: null,
      path: relativePath(root, evidencePath)
    };
  }

  return {
    exists: true,
    marketplaceEntryVersionSupported: /^marketplaceEntryVersionSupported:\s*true\s*$/m.test(text),
    marketplaceEntryVersionUnsupported: /^marketplaceEntryVersionSupported:\s*false\s*$/m.test(text),
    validatorUnavailable: /^validatorUnavailable:\s*true\s*$/m.test(text),
    validatorAvailable: /^validatorUnavailable:\s*false\s*$/m.test(text),
    path: relativePath(root, evidencePath)
  };
}

export function shouldExpectMarketplaceEntryVersion(start = process.cwd()) {
  const confirmation = versionAxisConfirmation(start);
  if (confirmation.marketplaceEntryVersionSupported) {
    return true;
  }
  if (confirmation.marketplaceEntryVersionUnsupported) {
    return false;
  }
  return DEFAULT_EXPECT_MARKETPLACE_ENTRY_VERSION;
}

function collectMachinePathFindings(root) {
  const patternContract = Boolean(MACHINE_PATH_PATTERN_SOURCE);
  return shippedTextFiles(root).flatMap((filePath) => {
    const text = fs.readFileSync(filePath, "utf8");
    if (!patternContract || !hasMachinePath(text)) {
      return [];
    }
    return text
      .split(/\r?\n/)
      .map((line, index) => ({ line, lineNumber: index + 1 }))
      .filter(({ line }) => hasMachinePath(line))
      .map(({ lineNumber }) => ({
        file: relativePath(root, filePath),
        line: lineNumber
      }));
  });
}

function commandFiles(root) {
  const commandsDir = path.join(root, CODEX_PLUGIN_DIR, "commands");
  if (!fs.existsSync(commandsDir)) {
    return [];
  }
  return fs
    .readdirSync(commandsDir, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".md"))
    .map((entry) => entry.name)
    .sort();
}

function docsInstallChecks(root) {
  const docs = [
    "README.md",
    path.join("docs", "README.en.md"),
    path.join("docs", "README.zh-CN.md"),
    path.join(CODEX_PLUGIN_DIR, "README.md")
  ];
  return docs.map((entry) => {
    const filePath = path.join(root, entry);
    const text = readTextIfExists(filePath);
    return {
      file: relativePath(root, filePath),
      ok: text != null && text.includes(INSTALL_COMMAND) && text.includes(INSTALL_TARGET)
    };
  });
}

function collectHookCommandEntries(hooks, hookName, failures) {
  const matchers = hooks.hooks?.[hookName];
  if (!Array.isArray(matchers) || matchers.length === 0) {
    failures.push(`${hookName} must be a non-empty hook matcher array.`);
    return [];
  }

  return matchers.flatMap((matcher, matcherIndex) => {
    if (!matcher || typeof matcher !== "object" || !Array.isArray(matcher.hooks) || matcher.hooks.length === 0) {
      failures.push(`${hookName}[${matcherIndex}].hooks must be a non-empty array.`);
      return [];
    }
    return matcher.hooks.map((hook) => ({ hook }));
  });
}

function isReasonableTimeout(timeout, expected) {
  return (
    typeof timeout === "number" &&
    Number.isFinite(timeout) &&
    timeout >= expected.minTimeout &&
    timeout <= expected.maxTimeout
  );
}

function normalizeCommandHookEntry(hook) {
  return {
    type: typeof hook?.type === "string" ? hook.type.trim() : hook?.type,
    command: typeof hook?.command === "string" ? hook.command.trim() : hook?.command
  };
}

function commandHookKey(entry) {
  return JSON.stringify([entry.type ?? null, entry.command ?? null]);
}

function uniqueCommandHookEntries(entries) {
  const seen = new Set();
  const unique = [];
  for (const entry of entries) {
    const key = commandHookKey(entry);
    if (!seen.has(key)) {
      seen.add(key);
      unique.push(entry);
    }
  }
  return unique;
}

function duplicateCommandHookEntries(entries) {
  const seen = new Set();
  const duplicates = [];
  for (const entry of entries) {
    const key = commandHookKey(entry);
    if (seen.has(key)) {
      duplicates.push(entry);
      continue;
    }
    seen.add(key);
  }
  return uniqueCommandHookEntries(duplicates);
}

function validateHookShape(hooks) {
  const failures = [];
  const actual = {};
  const requiredHookNames = Object.keys(EXPECTED_HOOK_COMMANDS).sort();
  const actualHookNames = Object.keys(hooks.hooks ?? {}).sort();

  if (!arraysEqual(actualHookNames, requiredHookNames)) {
    failures.push(`Hook events must be exactly: ${requiredHookNames.join(", ")}.`);
  }

  for (const [hookName, expected] of Object.entries(EXPECTED_HOOK_COMMANDS)) {
    const entries = collectHookCommandEntries(hooks, hookName, failures);
    const normalizedEntries = entries.map(({ hook }) => ({
      ...normalizeCommandHookEntry(hook),
      timeout: hook?.timeout
    }));
    actual[hookName] = normalizedEntries;

    const expectedEntry = { type: "command", command: expected.command };
    const expectedKeys = new Set([commandHookKey(expectedEntry)]);
    const unexpectedEntries = uniqueCommandHookEntries(
      normalizedEntries.filter((entry) => !expectedKeys.has(commandHookKey(entry)))
    );
    if (unexpectedEntries.length > 0) {
      failures.push(`${hookName} has unexpected command hook entries: ${JSON.stringify(unexpectedEntries)}`);
    }

    const duplicateEntries = duplicateCommandHookEntries(normalizedEntries);
    if (duplicateEntries.length > 0) {
      failures.push(`${hookName} has duplicate command hook entries: ${JSON.stringify(duplicateEntries)}`);
    }

    const matchingCommands = normalizedEntries.filter(
      (entry) => entry.type === expectedEntry.type && entry.command === expectedEntry.command
    );
    if (matchingCommands.length !== 1) {
      failures.push(`${hookName} must include exactly one command: ${expected.command}`);
      continue;
    }
    if (!isReasonableTimeout(matchingCommands[0].timeout, expected)) {
      failures.push(
        `${hookName} timeout must be between ${expected.minTimeout} and ${expected.maxTimeout} seconds.`
      );
    }
  }

  return {
    ok: failures.length === 0,
    detail: {
      required: requiredHookNames,
      actualEvents: actualHookNames,
      actual,
      failures
    }
  };
}

export function runReleaseCheck(start = null, options = {}) {
  start = start ?? process.cwd();
  const root = findRepoRoot(start);
  const marketplace = readJson(path.join(root, ".claude-plugin", "marketplace.json"));
  const manifest = readJson(path.join(root, CODEX_PLUGIN_DIR, ".claude-plugin", "plugin.json"));
  const codexEntries = (marketplace.plugins ?? []).filter((entry) => entry.name === "codex");
  const codexEntry = codexEntries.length === 1 ? codexEntries[0] : null;
  const expectMarketplaceEntryVersion = shouldExpectMarketplaceEntryVersion(root);
  const versionConfirmation = versionAxisConfirmation(root);
  const forkNotice = readTextIfExists(path.join(root, CODEX_PLUGIN_DIR, "FORK_NOTICE.md")) ?? "";
  const attribution =
    readTextIfExists(path.join(root, CODEX_PLUGIN_DIR, "AUTHOR_ATTRIBUTION_CONFIRMATION.md")) ?? "";
  const hooks = readJson(path.join(root, CODEX_PLUGIN_DIR, "hooks", "hooks.json"));
  const hookNames = Object.keys(hooks.hooks ?? {}).sort();
  const hookShape = validateHookShape(hooks);
  const actualCommands = commandFiles(root);
  const docs = docsInstallChecks(root);
  const machinePathFindings = collectMachinePathFindings(root);

  const checks = [
    check(
      "version-axis-confirmed",
      versionConfirmation.exists &&
        (versionConfirmation.marketplaceEntryVersionSupported ||
          versionConfirmation.marketplaceEntryVersionUnsupported) &&
        (versionConfirmation.validatorAvailable || versionConfirmation.validatorUnavailable),
      versionConfirmation
    ),
    check("marketplace-version", marketplace.metadata?.version === MARKETPLACE_VERSION, {
      expected: MARKETPLACE_VERSION,
      actual: marketplace.metadata?.version
    }),
    check("manifest-version", manifest.version === CODEX_VERSION, {
      expected: CODEX_VERSION,
      actual: manifest.version
    }),
    check(
      "marketplace-codex-entry",
      codexEntries.length === 1 &&
        codexEntry?.source === "./plugins/codex" &&
        (expectMarketplaceEntryVersion ? codexEntry.version === CODEX_VERSION : !("version" in codexEntry)),
      {
        matchingEntries: codexEntries.length,
        source: codexEntry?.source,
        expectedVersion: expectMarketplaceEntryVersion ? CODEX_VERSION : null,
        actualVersion: codexEntry?.version
      }
    ),
    check(
      "marketplace-codex-author",
      sameJson(codexEntry?.author, MARKETPLACE_CODEX_AUTHOR),
      codexEntry?.author ?? null
    ),
    check("plugin-codex-author", sameJson(manifest.author, PLUGIN_CODEX_AUTHOR), manifest.author ?? null),
    check(
      "author-attribution-confirmed",
      attribution.toLowerCase().includes("confirmed") && attribution.includes("OpenAI"),
      "plugins/codex/AUTHOR_ATTRIBUTION_CONFIRMATION.md"
    ),
    check(
      "fork-notice",
      forkNotice.includes("OpenAI-authored") &&
        forkNotice.includes("Apache-2.0") &&
        forkNotice.includes("unverified upstream lineage"),
      "plugins/codex/FORK_NOTICE.md"
    ),
    check("manifest-no-hooks-field", !Object.hasOwn(manifest, "hooks"), Object.hasOwn(manifest, "hooks")),
    check("hooks-shape", hookShape.ok, hookShape.ok ? hookNames : hookShape.detail),
    check("command-surface", arraysEqual(actualCommands, EXPECTED_COMMANDS), actualCommands),
    check(
      "ready-command-surface",
      READY_COMMANDS.every((name) => EXPECTED_COMMANDS.includes(name) && !PREVIEW_COMMANDS.has(name)) &&
        [...PREVIEW_COMMANDS].every((name) => EXPECTED_COMMANDS.includes(name)),
      READY_COMMANDS
    ),
    check("docs-install", docs.every((doc) => doc.ok), docs),
    check("no-machine-paths", machinePathFindings.length === 0, machinePathFindings)
  ];

  if (options.ciSimulate || options.requireCodexCli) {
    const workflow = renderWorkflow({ ref: "v0.2.0" });
    const workflowValidation = validateWorkflow(workflow);
    const workflowChecks = workflowValidation.checks;
    const requireCodexCli = Boolean(options.requireCodexCli);
    let claudeVersionOk = false;
    let codexVersionOk = false;
    let codexAuthOk = false;
    let claudeVersionDetail = "not verified; rerun with --require-codex-cli on the release host";
    let codexVersionDetail = "not verified; rerun with --require-codex-cli on the release host";
    let codexAuthDetail = "not verified; rerun with --require-codex-cli on the release host";

    if (requireCodexCli) {
      const claudeSentinel = CLAUDE_CODE_NPM_VERSION === "REPLACE_WITH_RELEASE_HOST_CLAUDE_CODE_VERSION";
      const codexSentinel = CODEX_CLI_NPM_VERSION === "REPLACE_WITH_RELEASE_HOST_CODEX_CLI_VERSION";
      if (claudeSentinel) {
        claudeVersionDetail = "sentinel not replaced: CLAUDE_CODE_NPM_VERSION";
      } else {
        const claudeVersionProbe = spawnSync(
          "npm",
          ["view", `@anthropic-ai/claude-code@${CLAUDE_CODE_NPM_VERSION}`, "version"],
          { encoding: "utf8", timeout: 5000 }
        );
        claudeVersionOk =
          claudeVersionProbe.status === 0 &&
          String(claudeVersionProbe.stdout || "").trim() === CLAUDE_CODE_NPM_VERSION;
        claudeVersionDetail = claudeVersionOk
          ? `verified npm @anthropic-ai/claude-code@${CLAUDE_CODE_NPM_VERSION}`
          : "required Claude Code npm version contract missing";
      }
      if (codexSentinel) {
        codexVersionDetail = "sentinel not replaced: CODEX_CLI_NPM_VERSION";
        codexAuthDetail = "skipped because CODEX_CLI_NPM_VERSION sentinel was not replaced";
      } else {
        const codexVersionProbe = spawnSync(
          "npm",
          ["view", `@openai/codex@${CODEX_CLI_NPM_VERSION}`, "version"],
          { encoding: "utf8", timeout: 5000 }
        );
        codexVersionOk =
          codexVersionProbe.status === 0 &&
          String(codexVersionProbe.stdout || "").trim() === CODEX_CLI_NPM_VERSION;
        const codexLoginHelp = spawnSync("codex", ["login", "--help"], {
          encoding: "utf8",
          timeout: 5000
        });
        const codexAvailable = !codexLoginHelp.error || codexLoginHelp.error.code !== "ENOENT";
        const codexAuthHelpOk =
          codexAvailable &&
          codexLoginHelp.status === 0 &&
          `${codexLoginHelp.stdout}\n${codexLoginHelp.stderr}`.includes("--with-api-key");
        const codexAuthProbe = codexAuthHelpOk
          ? probeCodexStdinLogin(process.env.OPENAI_API_KEY)
          : { ok: false, detail: "required Codex CLI auth contract missing" };
        codexAuthOk = codexAuthProbe.ok;
        codexVersionDetail = codexVersionOk
          ? `verified npm @openai/codex@${CODEX_CLI_NPM_VERSION}`
          : "required Codex CLI npm version contract missing";
        codexAuthDetail = codexAuthProbe.detail;
      }
    }

    const workflowCheckOk = (name) => workflowChecks.some((item) => item.name === name && item.ok);
    const workflowReadyContract = releaseHostContractsVerified();
    const failedWorkflowChecks = workflowChecks.filter((item) => !item.ok);
    checks.push(
      check(
        "ci-workflow-validation",
        requireCodexCli ? workflowValidation.ready : workflowValidation.structuralOk,
        failedWorkflowChecks
      ),
      check("ci-workflow-fork-safe", workflowCheckOk("fork-safe-step-gates")),
      check(
        "ci-workflow-codex-auth-login",
        !workflowReadyContract || workflowCheckOk("codex-auth-login"),
        workflowReadyContract ? "" : "preview: auth step omitted until release-host verification"
      ),
      check(
        "ci-workflow-codex-cli-version-pinned",
        !workflowReadyContract || workflowCheckOk("codex-cli-version-pinned"),
        workflowReadyContract ? "" : "preview: Codex CLI version sentinel not replaced"
      ),
      check(
        "ci-workflow-claude-code-version-pinned",
        !workflowReadyContract || workflowCheckOk("claude-code-version-pinned"),
        workflowReadyContract ? "" : "preview: Claude Code version sentinel not replaced"
      ),
      check("ci-workflow-plugin-root-resolved", workflowCheckOk("plugin-root-resolved")),
      check("ci-claude-code-version-contract", !requireCodexCli || claudeVersionOk, claudeVersionDetail),
      check("ci-codex-cli-version-contract", !requireCodexCli || codexVersionOk, codexVersionDetail),
      check("ci-codex-cli-auth-contract", !requireCodexCli || codexAuthOk, codexAuthDetail)
    );
  }

  return {
    ok: checks.every((item) => item.ok),
    checks
  };
}
