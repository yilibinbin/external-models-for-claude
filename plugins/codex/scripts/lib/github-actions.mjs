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

function result(ok, name, detail = "") {
  return { ok: Boolean(ok), name, detail };
}

function topLevelBlockLines(text, header) {
  const lines = text.split(/\r?\n/);
  const start = lines.findIndex((line) => line === header);
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

function hasMinimalContentsReadPermission(text) {
  const entries = topLevelBlockLines(text, "permissions:")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"));
  return entries.length === 1 && entries[0] === "contents: read";
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
  const checks = [
    result(text.includes("pull_request:"), "has-pull-request-trigger"),
    result(!text.includes("pull_request_target"), "no-pull-request-target"),
    result(hasMinimalContentsReadPermission(text), "minimal-contents-permission"),
    result(text.includes("claude plugin marketplace add \"$marketplace_dir\" --scope user"), "marketplace-install"),
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
    result(
      text.includes("steps.fork-safety.outputs.safe_to_review == 'true'") &&
        text.includes("Codex review skipped because pull request head repository is not this repository") &&
        text.includes('{"status":"skipped","reason":"external-head-repository"}'),
      "fork-safe-step-gates"
    ),
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
      releaseHostContractsVerified()
        ? text.includes("OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}") &&
            text.includes(CODEX_CLI_AUTH_HELP_COMMAND) &&
            text.includes(CODEX_CLI_AUTH_LOGIN_COMMAND)
        : text.includes("Codex auth steps omitted until release-host CLI/auth contract is verified."),
      "codex-auth-login"
    ),
    result(
      releaseHostContractsVerified()
        ? text.includes("$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs") &&
            text.includes('review --base "$BASE_SHA" --json')
        : text.includes("Codex review execution omitted until release-host CLI/auth contract is verified."),
      "codex-review-step"
    ),
    result(!text.includes("CODEX_API_KEY"), "no-unsupported-codex-api-key-env"),
    result(releaseHostContractsVerified() ? text.includes("$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs") : true, "runtime-path"),
    result(!text.includes("--dangerously-skip-permissions"), "no-dangerous-permission-flag"),
    result(!hasMachinePath(text), "no-local-absolute-paths")
  ];
  const readyCheckNames = new Set([
    "codex-cli-version-pinned",
    "claude-code-version-pinned",
    "codex-auth-login",
    "codex-review-step",
    "runtime-path"
  ]);
  const structuralOk = checks.every((item) => item.ok || (!releaseHostContractsVerified() && readyCheckNames.has(item.name)));
  const ready = structuralOk && releaseHostContractsVerified() && checks.every((item) => item.ok);
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
