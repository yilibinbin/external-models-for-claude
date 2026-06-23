---
description: Show Claude for Claude setup and job status diagnostic
argument-hint: '[--json]'
disable-model-invocation: true
allowed-tools: Bash(node:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Show Claude for Claude status for the current workspace.

Invocation:
```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" status
```

If the user supplied options, append them as separately quoted argv tokens.
