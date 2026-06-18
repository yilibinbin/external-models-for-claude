---
description: Manage Antigravity advisory mailbox threads
argument-hint: "<list|post|show> [--thread id] [--message text]"
disable-model-invocation: true
allowed-tools: Bash(node:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run `mailbox` through the installed Antigravity companion.

Parse raw arguments into independent argv tokens and invoke:
`${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs`

Return the companion output directly.
