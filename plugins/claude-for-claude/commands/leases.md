---
description: Manage Claude advisory leases
argument-hint: "<claim|list|release> [--role role] [--ttl-seconds n] [--id lease-id]"
disable-model-invocation: true
allowed-tools: Bash(node:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run `leases` through the installed Claude for Claude companion.

Parse raw arguments into independent argv tokens and invoke:
`${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs`

Command:
`leases`

Return the companion output directly.
