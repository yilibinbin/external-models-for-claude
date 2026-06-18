---
description: List Antigravity background jobs or inspect one job
argument-hint: "[job-id]"
disable-model-invocation: true
allowed-tools: Bash(node:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run `jobs` when no job id is supplied, otherwise run `status <job-id>`.

Parse raw arguments into independent argv tokens and invoke:
`${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs`

Return the companion output directly.
