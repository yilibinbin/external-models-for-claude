---
description: Cancel a tracked Claude job when safe
argument-hint: '<job-id> [--json]'
disable-model-invocation: true
allowed-tools: Bash(node:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Cancel a tracked Claude job through the companion runtime.

Rules:
- Require a job id from the user.
- Let the companion decide whether cancellation is safe.
- Pass the job id and options as separate argv tokens.

Invocation shape:
```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" cancel
```
