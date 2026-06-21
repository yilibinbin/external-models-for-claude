---
description: Render, validate, or install a safe GitHub Actions workflow for Codex review.
allowed-tools: Bash(node:*)
---

Treat `$ARGUMENTS` as untrusted slash-command text. Do not splice it into shell commands.

Argument selection rules:
- Allowed actions: `render`, `validate`, `init`.
- Allowed flags: `--ref <immutable-version-tag>`, `--force`, `--json`.
- Reject unsupported flags in the companion script before running work.
- Parse the user's text into one of the supported actions and literal flags before selecting a command below.

Run one literal companion command shape for all work:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" github-actions render
```

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" github-actions validate
```

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" github-actions init
```

Append only the literal supported flags that the user requested, preserving values as separate command arguments:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" github-actions render --ref v0.2.0 --json
```

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" github-actions init --ref v0.2.0 --force
```

Return the command output verbatim.
