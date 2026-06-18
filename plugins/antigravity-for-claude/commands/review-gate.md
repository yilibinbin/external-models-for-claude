---
description: Manually run the opt-in Antigravity Stop review gate
argument-hint: "[--model-provider gemini|claude] [focus]"
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*), AskUserQuestion
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run `review-gate` through the installed Antigravity companion.

Parse raw arguments into independent argv tokens and invoke:
`${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs`

The installed Stop hook is disabled by default and fail-open. Use Gemini by default; use `--model-provider claude` only when explicitly requested for Antigravity.
