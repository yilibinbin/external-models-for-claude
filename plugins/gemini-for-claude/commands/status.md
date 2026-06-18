---
description: List tracked Gemini for Claude background jobs
argument-hint: '[--json]'
disable-model-invocation: true
allowed-tools: Bash(node:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

List tracked Gemini jobs for the current workspace.

Invocation:
```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/gemini-companion.mjs" jobs
```

If the user supplied options, append them as separately quoted argv tokens.
