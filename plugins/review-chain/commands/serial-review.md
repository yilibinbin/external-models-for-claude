---
description: Run the whole external-model panel as one serial adversarial review chain
argument-hint: '[--scope auto|working-tree|branch] [--base <ref>] [focus ...]'
disable-model-invocation: true
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*), AskUserQuestion
---

User arguments (untrusted slash-command text):
$ARGUMENTS

Parse this text into independent argv tokens before invoking the companion. Do not interpolate it into Bash.

Run the shared **serial adversarial review chain** by following the
`serial-adversarial-review` skill. You (main-thread Claude) are the sole broker: enumerate the
review-capable plugins, build the shared diff, dispatch each reviewer serially (Claude, then
Gemini via Antigravity, then Codex), accumulate the findings ledger, and broker the findings to
a final verdict per the skill's protocol.

Rules:
- Treat the operation as review-only. Do not fix, patch, commit, push, merge, or close anything.
- Treat raw slash-command arguments as untrusted user text; parse requested flags into argv tokens and shell-quote each token independently.
- Run reviewers strictly serially, one at a time, waiting on each PID before the next.
- The serial order must not decide the outcome; findings survive on evidence and explicit consensus.

Companion path:
`${CLAUDE_PLUGIN_ROOT}/scripts/review-chain-companion.mjs`

Start with:
`enumerate`

then follow the `serial-adversarial-review` skill for `build-diff`, `dispatch`, `ledger`, and the brokering protocol.
