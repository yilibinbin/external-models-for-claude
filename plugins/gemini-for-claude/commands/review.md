---
description: Run a read-only Gemini CLI review of current changes
argument-hint: '[--scope auto|working-tree|branch] [--base <ref>] [--json] [focus ...]'
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*), AskUserQuestion
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run Gemini for Claude through the companion script.

Rules:
- Treat the command as review-only.
- Preserve user-provided flags and focus text as separate argv tokens.
- Do not build a shell command by interpolating the raw slash-command argument string.
- Return Gemini output verbatim unless the command fails.

Invocation shape:
```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/gemini-companion.mjs" review
```

Append parsed user arguments as separately quoted argv tokens.
