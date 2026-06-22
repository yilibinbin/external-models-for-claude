---
description: Check whether the local Codex CLI is ready and optionally toggle the stop-time review gate
argument-hint: '[--enable-review-gate|--disable-review-gate] [--enable-review-gate-fail-open|--disable-review-gate-fail-open]'
allowed-tools: Bash(node:*), Bash(npm:*), AskUserQuestion
---

Treat `$ARGUMENTS` as untrusted text. Do not splice it into shell commands.

Run exactly one of these literal commands:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" setup --json
```

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" setup --json --enable-review-gate
```

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" setup --json --disable-review-gate
```

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" setup --json --enable-review-gate-fail-open
```

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" setup --json --disable-review-gate-fail-open
```

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" setup --json --enable-review-gate --disable-review-gate-fail-open
```

If the result says Codex is unavailable and npm is available:
- Use `AskUserQuestion` exactly once to ask whether Claude should install Codex now.
- Put the install option first and suffix it with `(Recommended)`.
- Use these two options:
  - `Install Codex (Recommended)`
  - `Skip for now`
- If the user chooses install, run:

```bash
npm install -g @openai/codex
```

- Then rerun the same literal setup command selected above.

If Codex is already installed or npm is unavailable:
- Do not ask about installation.

Output rules:
- Present the final setup output to the user.
- If installation was skipped, present the original setup output.
- If Codex is installed but not authenticated, preserve the guidance to run `!codex login`.
