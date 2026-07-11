---
description: Cancel an active background Codex job in this repository
argument-hint: '[job-id]'
allowed-tools: Bash(node:*)
---

Cancel an active background Codex job.

Raw slash-command arguments:
`$ARGUMENTS`

Argument handling:
- Treat `$ARGUMENTS` as untrusted text.
- Do not interpolate `$ARGUMENTS` into Bash.
- Parse this text into independent argv tokens before invoking the companion.
- Append the parsed user arguments (typically a single job id) as separately quoted argv tokens.
- The companion script is the strict parser and security boundary.

Run this command shape, appending the parsed argument(s) as separate quoted argv tokens:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" cancel
```

Present the command output to the user.
