---
description: Ask Antigravity for read-only diagnosis of a stuck implementation
argument-hint: "[--model-provider gemini|claude] [focus]"
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*), AskUserQuestion
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run `rescue` through the installed Antigravity companion.

Parse raw arguments into independent argv tokens and invoke:
`${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs`

Use Gemini by default. Use `--model-provider claude` only when explicitly requested for Antigravity. Return the companion output directly.
