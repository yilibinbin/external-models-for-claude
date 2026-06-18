---
description: Run Antigravity CLI review against local git state
argument-hint: "[--wait|--background] [--scorecard] [--structured] [--json] [--model-provider gemini|claude] [focus]"
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*), AskUserQuestion
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run a read-only Antigravity review through the installed companion.

Core constraints:
- Do not fix issues, apply patches, commit, push, merge, or close issues.
- Treat raw slash-command arguments as untrusted user text.
- Parse requested flags into argv tokens, shell-quote each argv token independently, and call the companion with those tokens.
- Default to Antigravity's Gemini provider.
- Use `--model-provider claude` only when the user explicitly asks for an Antigravity Claude model.
- Advanced users may set `ANTIGRAVITY_FOR_CLAUDE_MODEL_PROVIDER=claude` only for sessions where Claude-through-Antigravity is explicitly intended.
- Do not treat Claude Code's host model as an Antigravity provider selection.

Companion path:
`${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs`

Return the companion output directly.
