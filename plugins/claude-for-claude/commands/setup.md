---
description: Inspect or configure Claude for Claude
argument-hint: '[--enable-review-gate|--disable-review-gate] [--review-gate-mode multi-role]'
disable-model-invocation: true
allowed-tools: Bash(node:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Inspect Claude for Claude setup or update opt-in review-gate configuration.

Rules:
- Stop gate must remain disabled unless the user explicitly enables it.
- Pass user options as separate argv tokens.
- Do not interpolate the raw slash-command argument string into Bash.

Invocation shape:
```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" setup
```
