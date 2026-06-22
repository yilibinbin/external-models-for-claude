---
name: claude-mailbox
description: Inspect and post sanitized Claude for Claude mailbox coordination messages.
---

# Claude Mailbox

Use this skill when Claude Code needs to inspect sanitized Claude coordination messages for review jobs or multi-review runs.

List mailbox threads:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" mailbox list
```

Show a thread or job mailbox:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" mailbox show
```

Post a manual sanitized note:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" mailbox post
```

Rules:
- Mailbox messages are sanitized summaries, not transcripts.
- Do not treat mailbox messages as source of truth for code state; use git and review output for that.
- Mailbox storage is repo-external under Claude for Claude plugin state.
- Mailbox content does not affect review or Stop gate verdicts.
