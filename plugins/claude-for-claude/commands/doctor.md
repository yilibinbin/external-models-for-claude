---
description: Diagnose Claude for Claude without running a review request
argument-hint: '[--json]'
disable-model-invocation: true
allowed-tools: Read, Bash(node:*), Bash(claude:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run Claude for Claude diagnostics through the companion script.

Rules:
- Do not start a model review.
- Preserve user-provided flags as separate argv tokens.
- Do not build a shell command by interpolating the raw slash-command argument string.
- Return the diagnostic output verbatim unless the command fails.

Invocation shape:
```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" doctor
```

Append parsed user arguments as separately quoted argv tokens.
