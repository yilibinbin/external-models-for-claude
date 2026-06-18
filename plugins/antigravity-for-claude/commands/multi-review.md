---
description: Run Antigravity multi-role review
argument-hint: "[--background] [--roles list|--role-pack name] [--scorecard] [--model-provider gemini|claude] [focus]"
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*), AskUserQuestion
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run `multi-review` through the installed Antigravity companion.

Core constraints:
- Keep the workflow read-only.
- Parse raw arguments into independent shell-quoted argv tokens.
- Use plugin-managed `--background` jobs instead of shell backgrounding when requested.
- Default to Antigravity's Gemini provider.
- Use `--model-provider claude` only when explicitly requested for Antigravity.

Companion path:
`${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs`

Return the job id or review output directly.
