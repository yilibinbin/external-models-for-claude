---
description: Cancel an Antigravity background job
argument-hint: "<job-id>"
disable-model-invocation: true
allowed-tools: Bash(node:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run `cancel <job-id>` through the installed Antigravity companion.

Parse the job id as one argv token and invoke:
`${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs`

Return the companion output directly.
