import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { hasMachinePath } from "./path-hygiene.mjs";

const WORKFLOW_RELATIVE_PATH = path.join(".github", "workflows", "codex-for-claude-review.yml");
export const CODEX_CLI_NPM_VERSION = "REPLACE_WITH_RELEASE_HOST_CODEX_CLI_VERSION";
export const CLAUDE_CODE_NPM_VERSION = "REPLACE_WITH_RELEASE_HOST_CLAUDE_CODE_VERSION";
export const RELEASE_HOST_CONTRACTS_VERIFIED = false;
export const CODEX_CLI_AUTH_HELP_COMMAND = "codex login --help 2>&1 | grep -qF -- '--with-api-key'";
export const CODEX_CLI_AUTH_LOGIN_COMMAND = "printenv OPENAI_API_KEY | codex login --with-api-key";
const PLUGIN_ROOT = path.resolve(fileURLToPath(new URL("..", import.meta.url)), "..");
const FORK_SAFE_IF = "if: steps.fork-safety.outputs.safe_to_review == 'true'";
const PLUGIN_ROOT_RESOLVER_SUBSTITUTION = 'CLAUDE_PLUGIN_ROOT="$(claude plugin list --json | node -e \'';

function result(ok, name, detail = "") {
  return { ok: Boolean(ok), name, detail };
}

function topLevelBlockLines(text, header) {
  const lines = text.split(/\r?\n/);
  const key = header.replace(/:$/, "");
  const keyPattern = new RegExp(`^(?:"${key}"|'${key}'|${key})\\s*:\\s*(?:#.*)?$`);
  const start = lines.findIndex((line) => keyPattern.test(line));
  if (start < 0) {
    return [];
  }
  const block = [];
  for (const line of lines.slice(start + 1)) {
    if (line.trim() && !line.startsWith(" ")) {
      break;
    }
    block.push(line);
  }
  return block;
}

function countTopLevelKey(text, key) {
  const pattern = new RegExp(`^(?:"${key}"|'${key}'|${key})\\s*:`, "gm");
  return [...text.matchAll(pattern)].length;
}

function activeWorkflowLines(text) {
  return text.split(/\r?\n/).filter((line) => !line.trim().startsWith("#"));
}

function leadingSpaces(line) {
  return line.match(/^ */)?.[0].length ?? 0;
}

function activeBlockStartingWith(text, trimmedStart) {
  if (trimmedStart.startsWith("- ")) {
    return activeStepBlocks(text).find((block) => block[0]?.trim() === trimmedStart) ?? [];
  }
  const lines = activeWorkflowLines(text);
  const start = lines.findIndex((line) => line.trim() === trimmedStart);
  if (start < 0) {
    return [];
  }
  const startIndent = leadingSpaces(lines[start]);
  const block = [];
  for (const line of lines.slice(start)) {
    if (block.length > 0 && line.trim() && leadingSpaces(line) <= startIndent) {
      break;
    }
    block.push(line);
  }
  return block;
}

function activeStepBlocks(text) {
  const lines = activeWorkflowLines(text);
  const blocks = [];
  for (let index = 0; index < lines.length; index += 1) {
    if (lines[index].trim() !== "steps:" || leadingSpaces(lines[index]) !== 4) {
      continue;
    }
    const stepsIndent = leadingSpaces(lines[index]);
    const itemIndent = lines
      .slice(index + 1)
      .find((line) => line.trim() && leadingSpaces(line) > stepsIndent && /^-\s+/.test(line.trim()));
    if (!itemIndent) {
      continue;
    }
    const stepIndent = leadingSpaces(itemIndent);
    let block = [];
    for (const line of lines.slice(index + 1)) {
      const trimmed = line.trim();
      const indent = leadingSpaces(line);
      if (trimmed && indent <= stepsIndent) {
        break;
      }
      if (indent === stepIndent && /^-\s+/.test(trimmed)) {
        if (block.length > 0) {
          blocks.push(block);
        }
        block = [line];
        continue;
      }
      if (block.length > 0) {
        block.push(line);
      }
    }
    if (block.length > 0) {
      blocks.push(block);
    }
  }
  return blocks;
}

function blockIncludesLine(text, trimmedStart, requiredLine) {
  const block = activeBlockStartingWith(text, trimmedStart);
  return blockHasFieldLine(block, requiredLine);
}

function blockHasFieldLine(block, requiredLine) {
  const firstIndent = leadingSpaces(block[0] ?? "");
  return block.some((line) => leadingSpaces(line) === firstIndent + 2 && line.trim() === requiredLine);
}

function hasUnexpectedCommandSubstitution(text) {
  return activeWorkflowLines(text).some((line) => {
    const trimmed = line.trim();
    return (
      (trimmed.includes("$(") && trimmed !== PLUGIN_ROOT_RESOLVER_SUBSTITUTION) ||
      trimmed.includes("`") ||
      /\$\{(?!\{)/.test(trimmed)
    );
  });
}

function hasMinimalContentsReadPermission(text) {
  const hasNestedPermissions = text.split(/\r?\n/).some((line) => /^\s+(?:"permissions"|'permissions'|permissions)\s*:\s*(?:.*)?$/.test(line));
  const entries = topLevelBlockLines(text, "permissions:")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
  return countTopLevelKey(text, "permissions") === 1 && !hasNestedPermissions && entries.length === 1 && entries[0] === "contents: read";
}

function hasPullRequestOnlyTrigger(text) {
  const entries = topLevelBlockLines(text, "on:")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
  return countTopLevelKey(text, "on") === 1 && entries.length === 1 && entries[0] === "pull_request:";
}

function hasSingleCodexReviewJob(text) {
  const entries = topLevelBlockLines(text, "jobs:")
    .filter((line) => /^\s{2}\S/.test(line))
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
  return countTopLevelKey(text, "jobs") === 1 && entries.length === 1 && entries[0] === "codex-review:";
}

function normalizedCommandText(text) {
  return text
    .replace(/\\\r?\n/g, "")
    .replace(/\$'((?:\\.|[^'])*)'/g, "$1")
    .replace(/\$"((?:\\.|[^"])*)"/g, "$1")
    .replace(/\\([^\r\n])/g, "$1")
    .replace(/["'`]/g, "")
    .replace(/\s+/g, " ");
}

function hasRunnableCodexAuthCommand(text) {
  return /(?:^|[\s;&|])(?:\S*\/)?codex\s+login\b[^;&|]*--with-api-key\b/.test(normalizedCommandText(text));
}

function hasRunnableCodexReviewCommand(text) {
  return /(?:^|[\s;&|])(?:node\s+)?\S*codex-companion\.mjs\s+review\b/.test(normalizedCommandText(text));
}

function hasAnsiQuotedShellFragment(text) {
  return /\$['"]/.test(text);
}

function hasImmutableMarketplaceInstall(text) {
  const block = activeBlockStartingWith(text, "- name: Install Codex for Claude plugin");
  const lines = block.map((line) => line.trim()).filter(Boolean);
  const blockText = block.join("\n");
  const expectedGitCommands = [
    'git init "$marketplace_dir"',
    'git -C "$marketplace_dir" remote add origin https://github.com/yilibinbin/external-models-for-claude',
    'git -C "$marketplace_dir" fetch --depth 1 origin "refs/tags/$CODEX_FOR_CLAUDE_RELEASE_REF"',
    'git -C "$marketplace_dir" checkout FETCH_HEAD'
  ];
  const gitLines = lines.filter((line) => /(?:^|[\s;&|])(?:\S*\/)?git\b/.test(normalizedCommandText(line)));
  return (
    gitLines.length === expectedGitCommands.length &&
    expectedGitCommands.every((command, index) => gitLines[index] === command) &&
    blockText.includes("claude plugin marketplace add \"$marketplace_dir\" --scope user") &&
    blockText.includes("claude plugin install codex@external-models-for-claude --scope user")
  );
}

function hasReviewArtifactUpload(text) {
  const block = activeBlockStartingWith(text, "- uses: actions/upload-artifact@v4")
    .map((line) => line.trim())
    .filter(Boolean);
  return (
    block.includes("- uses: actions/upload-artifact@v4") &&
    block.includes("if: always()") &&
    block.includes("name: codex-for-claude-review") &&
    block.includes("path: codex-for-claude-review.*")
  );
}

function expectedForkSafetyDetectorBlock() {
  return [
    "- name: Detect fork safety",
    "id: fork-safety",
    "shell: bash",
    "run: |",
    'if [ "$IS_FORK" = "true" ] || [ "$HEAD_REPO" != "$BASE_REPO" ]; then',
    'echo "safe_to_review=false" >> "$GITHUB_OUTPUT"',
    'echo "Codex review skipped because pull request head repository is not this repository." > codex-for-claude-review.md',
    'printf \'%s\\n\' \'{"status":"skipped","reason":"external-head-repository"}\' > codex-for-claude-review.json',
    "else",
    'echo "safe_to_review=true" >> "$GITHUB_OUTPUT"',
    "fi"
  ];
}

function blockMatchesExpected(block, expected) {
  const normalized = block.map((line) => line.trim()).filter(Boolean);
  return normalized.length === expected.length && expected.every((line, index) => normalized[index] === line);
}

function matchingForkSafetyDetectorCount(text) {
  const expected = expectedForkSafetyDetectorBlock();
  return activeStepBlocks(text).filter((block) => blockMatchesExpected(block, expected)).length;
}

function hasActiveForkSafetyDetector(text) {
  return matchingForkSafetyDetectorCount(text) === 1;
}

function expectedPluginInstallBlock() {
  return [
    "- name: Install Codex for Claude plugin",
    FORK_SAFE_IF,
    "run: |",
    'marketplace_dir="$RUNNER_TEMP/external-models-for-claude"',
    'git init "$marketplace_dir"',
    'git -C "$marketplace_dir" remote add origin https://github.com/yilibinbin/external-models-for-claude',
    'git -C "$marketplace_dir" fetch --depth 1 origin "refs/tags/$CODEX_FOR_CLAUDE_RELEASE_REF"',
    'git -C "$marketplace_dir" checkout FETCH_HEAD',
    'claude plugin marketplace add "$marketplace_dir" --scope user',
    "claude plugin install codex@external-models-for-claude --scope user"
  ];
}

function expectedPluginRootResolverBlock() {
  return [
    "- name: Resolve installed plugin root",
    FORK_SAFE_IF,
    "run: |",
    'CLAUDE_PLUGIN_ROOT="$(claude plugin list --json | node -e \'',
    "// codex-plugin-root-resolver-begin",
    'const fs = require("fs");',
    'const data = JSON.parse(fs.' + 'readFileSync(0, "utf8"));',
    "const plugins = Array.isArray(data) ? data : data.plugins || [];",
    'const plugin = plugins.find((item) => item.id === "codex@external-models-for-claude") || plugins.find((item) => item.name === "codex");',
    "const root = plugin && (plugin.installPath || plugin.path || plugin.root);",
    "if (!root) {",
    "console" + '.error("Could not resolve codex@external-models-for-claude install root from claude plugin list --json.");',
    "process.exit(1);",
    "}",
    "process." + "stdout.write(root);",
    "// codex-plugin-root-resolver-end",
    `')"`,
    'echo "CLAUDE_PLUGIN_ROOT=$CLAUDE_PLUGIN_ROOT" >> "$GITHUB_ENV"'
  ];
}

function expectedCodexAuthBlocks() {
  return [
    [
      "- name: Verify Codex API-key login support",
      FORK_SAFE_IF,
      `run: "${CODEX_CLI_AUTH_HELP_COMMAND}"`
    ],
    [
      "- name: Authenticate Codex",
      FORK_SAFE_IF,
      "env:",
      "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}",
      "shell: bash",
      "run: |",
      'if [ -z "$OPENAI_API_KEY" ]; then',
      'echo "OPENAI_API_KEY secret is required for internal pull-request review." >&2',
      "exit 1",
      "fi",
      CODEX_CLI_AUTH_LOGIN_COMMAND
    ]
  ];
}

function expectedCodexReviewBlock(contractsVerified) {
  if (!contractsVerified) {
    return [
      "- name: Preview Codex review",
      FORK_SAFE_IF,
      "shell: bash",
      "run: |",
      'echo "Codex review execution omitted until release-host CLI/auth contract is verified."',
      `printf '%s\\n' '{"status":"preview","reason":"release-host-cli-auth-contract-unverified"}' > codex-for-claude-review.json`
    ];
  }
  return [
    "- name: Run Codex review",
    FORK_SAFE_IF,
    "shell: bash",
    "run: |",
    "set +e",
    'node "$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs" review --base "$BASE_SHA" --json > codex-for-claude-review.json 2> codex-for-claude-review.stderr',
    "status=$?",
    'if [ "$status" -ne 0 ]; then',
    "node -e '",
    'const fs = require("fs");',
    "const status = Number(process.argv[1]);",
    'const stderr = fs.existsSync("codex-for-claude-review.stderr") ? fs.' + 'readFileSync("codex-for-claude-review.stderr", "utf8").trim() : "";',
    'fs.writeFileSync("codex-for-claude-review.json", JSON.stringify({status: "failed", exitStatus: status, stderr}, null, 2) + "\\n");',
    `' "$status"`,
    'exit "$status"',
    "fi"
  ];
}

function expectedStepBlocks(contractsVerified) {
  return [
    [
      "- uses: actions/checkout@v4",
      "with:",
      "fetch-depth: 0"
    ],
    expectedForkSafetyDetectorBlock(),
    [
      "- uses: actions/setup-node@v4",
      FORK_SAFE_IF,
      "with:",
      'node-version: "20"'
    ],
    [
      "- name: Install Claude Code",
      FORK_SAFE_IF,
      'run: npm install -g "@anthropic-ai/claude-code@$CLAUDE_CODE_NPM_VERSION"'
    ],
    [
      "- name: Install Codex CLI",
      FORK_SAFE_IF,
      'run: npm install -g "@openai/codex@$CODEX_CLI_NPM_VERSION"'
    ],
    ...(contractsVerified ? expectedCodexAuthBlocks() : []),
    expectedPluginInstallBlock(),
    expectedPluginRootResolverBlock(),
    expectedCodexReviewBlock(contractsVerified),
    [
      "- uses: actions/upload-artifact@v4",
      "if: always()",
      "with:",
      "name: codex-for-claude-review",
      "path: codex-for-claude-review.*",
      "retention-days: 5"
    ]
  ];
}

function hasExpectedStepBlocks(text, contractsVerified) {
  const actual = activeStepBlocks(text);
  const expected = expectedStepBlocks(contractsVerified);
  return actual.length === expected.length && expected.every((block, index) => blockMatchesExpected(actual[index], block));
}

function hasForkSafeStepGates(text, contractsVerified) {
  const requiredSteps = [
    "- uses: actions/setup-node@v4",
    "- name: Install Claude Code",
    "- name: Install Codex CLI",
    "- name: Install Codex for Claude plugin",
    "- name: Resolve installed plugin root",
    contractsVerified ? "- name: Verify Codex API-key login support" : null,
    contractsVerified ? "- name: Authenticate Codex" : null,
    contractsVerified ? "- name: Run Codex review" : "- name: Preview Codex review"
  ].filter(Boolean);
  const requiredStepsGated = requiredSteps.every((step) => blockIncludesLine(text, step, FORK_SAFE_IF));
  const allowedUngatedSteps = new Set([
    "- uses: actions/checkout@v4",
    "- uses: actions/upload-artifact@v4"
  ]);
  const expectedDetector = expectedForkSafetyDetectorBlock();
  const executableStepsGated = activeStepBlocks(text).every((block) => {
    const firstLine = block[0]?.trim() ?? "";
    const hasExecutableSurface =
      firstLine.startsWith("- uses:") ||
      firstLine.startsWith("- run:") ||
      block.some((line) => line.trim().startsWith("run:"));
    return (
      !hasExecutableSurface ||
      allowedUngatedSteps.has(firstLine) ||
      blockMatchesExpected(block, expectedDetector) ||
      blockHasFieldLine(block, FORK_SAFE_IF)
    );
  });
  return hasExpectedStepBlocks(text, contractsVerified) && hasActiveForkSafetyDetector(text) && requiredStepsGated && executableStepsGated;
}

export function validateReleaseRef(value) {
  const ref = String(value ?? "v0.2.0").trim();
  const lower = ref.toLowerCase();
  if (!ref || lower === "main" || lower === "master" || lower === "head" || lower.startsWith("refs/heads/")) {
    throw new Error("--ref must be an immutable version tag like v0.2.0.");
  }
  if (!/^v\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?$/.test(ref)) {
    throw new Error("--ref must be an immutable version tag like v0.2.0.");
  }
  return ref;
}

export function releaseHostContractsVerified() {
  return (
    RELEASE_HOST_CONTRACTS_VERIFIED === true &&
    CODEX_CLI_NPM_VERSION !== "REPLACE_WITH_RELEASE_HOST_CODEX_CLI_VERSION" &&
    CLAUDE_CODE_NPM_VERSION !== "REPLACE_WITH_RELEASE_HOST_CLAUDE_CODE_VERSION"
  );
}

export function versionSentinelsPaired() {
  const codexSentinel = CODEX_CLI_NPM_VERSION === "REPLACE_WITH_RELEASE_HOST_CODEX_CLI_VERSION";
  const claudeSentinel = CLAUDE_CODE_NPM_VERSION === "REPLACE_WITH_RELEASE_HOST_CLAUDE_CODE_VERSION";
  return codexSentinel === claudeSentinel;
}

export function renderWorkflow(options = {}) {
  const ref = validateReleaseRef(options.ref);
  return fs.readFileSync(path.join(PLUGIN_ROOT, "templates", "github-actions", "codex-review.yml"), "utf8")
    .replaceAll("{{RELEASE_REF}}", ref)
    .replaceAll("{{CODEX_CLI_NPM_VERSION}}", CODEX_CLI_NPM_VERSION)
    .replaceAll("{{CLAUDE_CODE_NPM_VERSION}}", CLAUDE_CODE_NPM_VERSION)
    .replaceAll("{{CODEX_AUTH_STEPS}}", renderCodexAuthSteps())
    .replaceAll("{{CODEX_REVIEW_STEP}}", renderCodexReviewStep());
}

export function renderCodexAuthSteps() {
  if (!releaseHostContractsVerified()) {
    return [
      "      # Codex auth steps omitted until release-host CLI/auth contract is verified.",
      "      # Replace CODEX_CLI_NPM_VERSION and CLAUDE_CODE_NPM_VERSION before rendering a ready workflow."
    ].join("\n");
  }
  return [
    "      - name: Verify Codex API-key login support",
    "        if: steps.fork-safety.outputs.safe_to_review == 'true'",
    `        run: "${CODEX_CLI_AUTH_HELP_COMMAND}"`,
    "      - name: Authenticate Codex",
    "        if: steps.fork-safety.outputs.safe_to_review == 'true'",
    "        env:",
    "          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}",
    "        shell: bash",
    "        run: |",
    "          if [ -z \"$OPENAI_API_KEY\" ]; then",
    "            echo \"OPENAI_API_KEY secret is required for internal pull-request review.\" >&2",
    "            exit 1",
    "          fi",
    `          ${CODEX_CLI_AUTH_LOGIN_COMMAND}`
  ].join("\n");
}

export function renderCodexReviewStep() {
  if (!releaseHostContractsVerified()) {
    return [
      "      - name: Preview Codex review",
      "        if: steps.fork-safety.outputs.safe_to_review == 'true'",
      "        shell: bash",
      "        run: |",
      "          echo \"Codex review execution omitted until release-host CLI/auth contract is verified.\"",
      "          printf '%s\\n' '{\"status\":\"preview\",\"reason\":\"release-host-cli-auth-contract-unverified\"}' > codex-for-claude-review.json"
    ].join("\n");
  }
  return [
    "      - name: Run Codex review",
    "        if: steps.fork-safety.outputs.safe_to_review == 'true'",
    "        shell: bash",
    "        run: |",
    "          set +e",
    "          node \"$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs\" review --base \"$BASE_SHA\" --json > codex-for-claude-review.json 2> codex-for-claude-review.stderr",
    "          status=$?",
    "          if [ \"$status\" -ne 0 ]; then",
    "            node -e '",
    "            const fs = require(\"fs\");",
    "            const status = Number(process.argv[1]);",
    "            const stderr = fs.existsSync(\"codex-for-claude-review.stderr\") ? fs.readFileSync(\"codex-for-claude-review.stderr\", \"utf8\").trim() : \"\";",
    "            fs.writeFileSync(\"codex-for-claude-review.json\", JSON.stringify({status: \"failed\", exitStatus: status, stderr}, null, 2) + \"\\n\");",
    "            ' \"$status\"",
    "            exit \"$status\"",
    "          fi"
  ].join("\n");
}

export function validateWorkflow(text) {
  const contractsVerified = releaseHostContractsVerified();
  const previewAuthSafe =
    !text.includes("OPENAI_API_KEY") &&
    !text.includes(CODEX_CLI_AUTH_HELP_COMMAND) &&
    !text.includes(CODEX_CLI_AUTH_LOGIN_COMMAND) &&
    !hasRunnableCodexAuthCommand(text) &&
    !hasAnsiQuotedShellFragment(text) &&
    !hasUnexpectedCommandSubstitution(text);
  const previewReviewSafe =
    !hasRunnableCodexReviewCommand(text) &&
    !hasAnsiQuotedShellFragment(text) &&
    !hasUnexpectedCommandSubstitution(text);
  const checks = [
    result(hasPullRequestOnlyTrigger(text), "has-pull-request-trigger"),
    result(hasSingleCodexReviewJob(text), "single-codex-review-job"),
    result(!text.includes("pull_request_target"), "no-pull-request-target"),
    result(hasMinimalContentsReadPermission(text), "minimal-contents-permission"),
    result(hasImmutableMarketplaceInstall(text), "marketplace-install"),
    result(text.includes("claude plugin install codex@external-models-for-claude --scope user"), "plugin-install"),
    result(
      text.includes("claude plugin list --json") &&
        text.includes("installPath") &&
        text.includes("plugin.path") &&
        text.includes("plugin.root"),
      "plugin-root-resolved"
    ),
    result(
      text.includes("HEAD_REPO: ${{ github.event.pull_request.head.repo.full_name }}") &&
        text.includes("BASE_REPO: ${{ github.repository }}"),
      "fork-env-mapping"
    ),
    result(hasForkSafeStepGates(text, contractsVerified), "fork-safe-step-gates"),
    result(
      /CODEX_CLI_NPM_VERSION: "[0-9]+\.[0-9]+\.[0-9]+"/.test(text) &&
        CODEX_CLI_NPM_VERSION !== "REPLACE_WITH_RELEASE_HOST_CODEX_CLI_VERSION" &&
        text.includes('npm install -g "@openai/codex@$CODEX_CLI_NPM_VERSION"'),
      "codex-cli-version-pinned"
    ),
    result(
      /CLAUDE_CODE_NPM_VERSION: "[0-9]+\.[0-9]+\.[0-9]+"/.test(text) &&
        CLAUDE_CODE_NPM_VERSION !== "REPLACE_WITH_RELEASE_HOST_CLAUDE_CODE_VERSION" &&
        text.includes('npm install -g "@anthropic-ai/claude-code@$CLAUDE_CODE_NPM_VERSION"'),
      "claude-code-version-pinned"
    ),
    result(versionSentinelsPaired(), "cli-version-sentinels-paired"),
    result(
      contractsVerified
        ? text.includes("OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}") &&
            text.includes(CODEX_CLI_AUTH_HELP_COMMAND) &&
            text.includes(CODEX_CLI_AUTH_LOGIN_COMMAND)
        : text.includes("Codex auth steps omitted until release-host CLI/auth contract is verified.") && previewAuthSafe,
      "codex-auth-login"
    ),
    result(
      contractsVerified
        ? text.includes("$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs") &&
            text.includes('review --base "$BASE_SHA" --json')
        : text.includes("Codex review execution omitted until release-host CLI/auth contract is verified.") &&
            previewReviewSafe,
      "codex-review-step"
    ),
    result(!text.includes("CODEX_API_KEY"), "no-unsupported-codex-api-key-env"),
    result(contractsVerified ? text.includes("$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs") : true, "runtime-path"),
    result(!text.includes("--dangerously-skip-permissions"), "no-dangerous-permission-flag"),
    result(hasReviewArtifactUpload(text), "review-artifact-upload"),
    result(!hasMachinePath(text), "no-local-absolute-paths")
  ];
  const readyCheckNames = new Set([
    "codex-cli-version-pinned",
    "claude-code-version-pinned",
    "runtime-path"
  ]);
  const structuralOk = checks.every((item) => item.ok || (!contractsVerified && readyCheckNames.has(item.name)));
  const ready = structuralOk && contractsVerified && checks.every((item) => item.ok);
  const preview = structuralOk && !ready;
  return { ok: ready, ready, preview, structuralOk, checks };
}

export function workflowPath(cwd = process.cwd()) {
  return path.join(cwd, WORKFLOW_RELATIVE_PATH);
}

export function writeWorkflow(cwd, text, options = {}) {
  const target = workflowPath(cwd);
  if (fs.existsSync(target) && !options.force) {
    throw new Error(`${WORKFLOW_RELATIVE_PATH} already exists; pass --force to overwrite.`);
  }
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, text, "utf8");
  return target;
}
