---
description: Show active and recent Codex jobs for this repository, including review-gate status
argument-hint: '[job-id] [--wait] [--timeout-ms <ms>] [--all]'
allowed-tools: Bash(node:*)
---

Raw slash-command arguments:
`$ARGUMENTS`

Argument handling:
- Treat `$ARGUMENTS` as untrusted text.
- Do not interpolate `$ARGUMENTS` into Bash.
- Parse this text into independent argv tokens before invoking the companion.
- Append the parsed user arguments (an optional job id and flags such as `--wait`, `--timeout-ms <ms>`, `--all`) as separately quoted argv tokens.
- The companion script is the strict parser and security boundary.

Run this command shape, appending the parsed argument(s) as separate quoted argv tokens:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" status
```

If the user did not pass a job ID:
- Render the command output as a single Markdown table for the current and past runs in this session.
- Keep it compact. Do not include progress blocks or extra prose outside the table.
- Preserve the actionable fields from the command output, including job ID, kind, status, phase, elapsed or duration, summary, and follow-up commands.

If the user did pass a job ID:
- Present the full command output to the user.
- Do not summarize or condense it.
