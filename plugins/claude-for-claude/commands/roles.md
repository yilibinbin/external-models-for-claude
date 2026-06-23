---
description: List Claude reviewer role packs
argument-hint: '[list|inspect <pack>|validate <file>] [--json]'
disable-model-invocation: true
allowed-tools: Bash(node:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

List Claude for Claude reviewer roles and role packs through the companion script.

Rules:
- Pass user options as separate argv tokens.
- Do not interpolate raw slash-command arguments into Bash.

Companion path:
`${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs`

Command:
`roles list`

Use `roles inspect <pack>` or `roles validate <file>` when the user asks to inspect or validate a specific role pack. Return the companion output directly.
