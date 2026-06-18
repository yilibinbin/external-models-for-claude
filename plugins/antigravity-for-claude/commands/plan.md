---
description: Ask Antigravity for an independent implementation plan
argument-hint: "[--taskset] [--model-provider gemini|claude] [focus]"
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*), AskUserQuestion
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run `plan` through the installed Antigravity companion without editing files.

Parse arguments into independent argv tokens and invoke:
`${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs`

Use Gemini by default. Use `--model-provider claude` only when explicitly requested for Antigravity. Return the companion output directly.
