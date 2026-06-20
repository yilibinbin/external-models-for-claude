---
description: Ask Claude for read-only diagnosis of a stuck implementation
argument-hint: "[--scope auto|working-tree|branch] [--base <ref>] [focus ...]"
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*), AskUserQuestion
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run `rescue` through the installed Claude for Claude companion.

Parse raw arguments into independent argv tokens and invoke:
`${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs`

Command:
`rescue`

Return the companion output directly.
