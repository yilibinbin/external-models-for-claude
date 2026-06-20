---
description: Manage Claude advisory mailbox threads
argument-hint: "<list|post|show> [--thread id] [--message text]"
disable-model-invocation: true
allowed-tools: Bash(node:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run `mailbox` through the installed Claude for Claude companion.

Parse raw arguments into independent argv tokens and invoke:
`${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs`

Command:
`mailbox`

Return the companion output directly.
