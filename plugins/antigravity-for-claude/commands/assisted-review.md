---
description: Run a bounded Antigravity scorecard review loop
argument-hint: "[--taskset <id>] [--max-review-rounds 1..3] [--model-provider gemini|claude] [focus]"
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*), AskUserQuestion
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run `assisted-review` through the installed Antigravity companion.

Keep the loop advisory and read-only; do not apply fixes. Parse raw arguments into independent argv tokens and invoke:
`${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs`

Default to Gemini. Use `--model-provider claude` only when explicitly requested for Antigravity. Return the companion output directly.
