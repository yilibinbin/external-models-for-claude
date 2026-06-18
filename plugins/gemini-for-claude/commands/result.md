---
description: Show a tracked Gemini job result
argument-hint: '<job-id> [--json]'
disable-model-invocation: true
allowed-tools: Bash(node:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Show a stored Gemini job result.

Rules:
- Require a job id from the user.
- Pass the job id and options as separate argv tokens.

Invocation shape:
```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/gemini-companion.mjs" result
```
