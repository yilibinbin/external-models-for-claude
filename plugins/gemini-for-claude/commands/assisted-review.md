---
description: Run a bounded Gemini scorecard review loop
argument-hint: '[--max-rounds <n>] [--score-threshold <n>] [focus ...]'
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*), AskUserQuestion
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run the bounded assisted-review workflow.

Rules:
- Gemini provides advisory findings only.
- Claude Code decides whether follow-up edits are warranted.
- Do not interpolate the raw slash-command argument string into Bash.

Invocation shape:
```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/gemini-companion.mjs" assisted-review
```

Append parsed user arguments as separately quoted argv tokens.
