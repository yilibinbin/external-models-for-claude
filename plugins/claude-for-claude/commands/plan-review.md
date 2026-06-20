---
description: Ask Claude to review a local implementation plan
argument-hint: '--plan <path> [--json] [focus ...]'
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run a read-only Claude review of a local plan file.

Rules:
- Require a plan path from the user.
- Pass the path and any focus text as separate argv tokens.
- Do not interpolate the raw slash-command argument string into Bash.

Invocation shape:
```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" plan-review
```

Append parsed user arguments as separately quoted argv tokens.
