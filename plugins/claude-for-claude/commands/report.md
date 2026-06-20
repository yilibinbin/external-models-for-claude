---
description: Show the latest sanitized Claude operation report
argument-hint: "--latest"
disable-model-invocation: true
allowed-tools: Bash(node:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run `report` through the installed Claude for Claude companion.

Parse raw arguments into independent argv tokens and invoke:
`${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs`

Command:
`report`

Return the companion output directly.
