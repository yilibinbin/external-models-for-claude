---
description: Configure or run the opt-in Claude for Claude stop-time review gate
argument-hint: '[--enable|--disable|--status] [--roles <list>|--role-pack <pack>]'
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run Claude for Claude review gate operations through the companion script.

Rules:
- Treat gate execution as read-only.
- Preserve user-provided flags and role selectors as separate argv tokens.
- Do not build a shell command by interpolating the raw slash-command argument string.
- Return the companion output verbatim unless the command fails.

Invocation shape:
```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" review-gate
```

Append parsed user arguments as separately quoted argv tokens.
