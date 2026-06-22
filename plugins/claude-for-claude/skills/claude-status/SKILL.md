---
name: claude-status
description: List Claude for Claude tracked background jobs for the current workspace.
---

# Claude Status

Use this skill when Claude Code needs to see Claude for Claude job lifecycle state without running a new review.

Run:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" jobs
```

Rules:
- Treat this as job status only.
- Do not confuse it with the runtime `status` diagnostic command, which checks live Claude agents and setup health.
- If no jobs are listed, say there are no tracked Claude jobs for this workspace.

Claude CLI sessions:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" sessions
```

Use `sessions` only when the user asks about Claude native CLI sessions. It is capability-gated by the installed Claude CLI.
