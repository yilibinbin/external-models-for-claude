---
description: Show the stored final output for a finished Codex job in this repository
argument-hint: '[job-id]'
allowed-tools: Bash(node:*)
---

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
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" result
```

Present the full command output to the user. Do not summarize or condense it. Preserve all details including:
- Job ID and status
- The complete result payload, including verdict, summary, findings, details, artifacts, and next steps
- File paths and line numbers exactly as reported
- Any error messages or parse errors
- Follow-up commands such as `/codex:status <id>` and `/codex:review`
