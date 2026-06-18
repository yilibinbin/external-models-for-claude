---
description: Show Antigravity for Claude setup and capability diagnostics
argument-hint: "[--json]"
disable-model-invocation: true
allowed-tools: Bash(node:*), Bash(git:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run `setup` through the installed Antigravity companion.

Parse raw arguments into independent argv tokens and invoke:
`${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs`

Return the companion output directly.
