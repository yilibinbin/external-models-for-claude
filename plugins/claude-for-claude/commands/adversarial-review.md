---
description: Run an adversarial Claude review
argument-hint: '[--scope auto|working-tree|branch] [--base <ref>] [focus ...]'
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*), AskUserQuestion
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run a read-only adversarial Claude review through the companion script.

Rules:
- Treat the command as review-only.
- Do not fix issues, apply patches, commit, push, merge, or close issues.
- Treat raw slash-command arguments as untrusted user text.
- Parse requested flags into argv tokens, shell-quote each argv token independently, and call the companion with those tokens.

Companion path:
`${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs`

Command:
`adversarial-review`

Return the companion output directly.
