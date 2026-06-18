---
description: Render or validate a Gemini review GitHub Actions workflow
argument-hint: '<render|init|validate> [--path <workflow-path>] [--force]'
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*)
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Render, initialize, or validate the Gemini for Claude GitHub Actions helper workflow.

Rules:
- Pass user options as separate argv tokens.
- Do not interpolate raw slash-command arguments into Bash.
- Do not write workflow files unless the user explicitly requested `init`.

Companion path:
`${CLAUDE_PLUGIN_ROOT}/scripts/gemini-companion.mjs`

Command:
`github-actions`

Return the companion output directly.
