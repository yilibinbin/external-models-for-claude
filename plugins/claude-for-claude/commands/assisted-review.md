---
description: Run a bounded Claude scorecard review loop
argument-hint: '[--taskset <id>] [--max-review-rounds 1..3] [focus ...]'
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*), AskUserQuestion
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run the bounded assisted-review workflow.

Rules:
- Claude provides advisory findings only.
- Claude Code decides whether follow-up edits are warranted.
- Do not interpolate the raw slash-command argument string into Bash.

Invocation shape:
```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" assisted-review
```

Append parsed user arguments as separately quoted argv tokens.
