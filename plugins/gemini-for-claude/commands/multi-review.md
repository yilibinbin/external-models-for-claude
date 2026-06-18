---
description: Run a multi-role read-only Gemini review
argument-hint: '[--role-pack <name>] [--agent-team plugin|native-agents] [focus ...]'
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*), AskUserQuestion
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run a Gemini multi-role review through the companion script.

Rules:
- Preserve user-provided options as argv tokens.
- Do not apply fixes or edit files from review findings.
- Do not interpolate the raw slash-command argument string into Bash.

Invocation shape:
```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/gemini-companion.mjs" multi-review
```

Append parsed user arguments as separately quoted argv tokens.
