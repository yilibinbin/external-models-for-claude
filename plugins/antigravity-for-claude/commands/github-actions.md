---
description: Render, initialize, or validate Antigravity GitHub Actions review workflow
argument-hint: "<render|init|validate> [--force] [--model-provider gemini|claude] [--ref tag] [--path file]"
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*), AskUserQuestion
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run `github-actions` through the installed Antigravity companion.

Parse raw arguments into independent argv tokens and invoke:
`${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs`

Default generated workflows to Gemini unless `--model-provider claude` is explicitly requested for Antigravity. Return the companion output directly.
