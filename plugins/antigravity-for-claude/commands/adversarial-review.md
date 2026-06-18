---
description: Run a skeptical Antigravity adversarial review
argument-hint: "[--scorecard] [--structured] [--json] [--model-provider gemini|claude] [focus]"
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*), AskUserQuestion
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run `adversarial-review` through the installed Antigravity companion.

Keep the operation read-only. Parse raw arguments into independent argv tokens and invoke:
`${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs`

Use Gemini unless the user explicitly asks for `--model-provider claude`. Return the companion output directly.
