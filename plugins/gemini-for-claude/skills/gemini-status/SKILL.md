---
name: gemini-status
description: List Gemini for Claude tracked background jobs for the current workspace.
---

# Gemini Status

Use this skill when Claude Code needs to see Gemini for Claude job lifecycle state without running a new review.

Run:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/gemini-companion.mjs" jobs
```

Rules:
- Treat this as job status only.
- Do not confuse it with the runtime `status` diagnostic command, which checks live Gemini agents and setup health.
- If no jobs are listed, say there are no tracked Gemini jobs for this workspace.

Gemini CLI sessions:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/gemini-companion.mjs" sessions
```

Use `sessions` only when the user asks about Gemini native CLI sessions. It is capability-gated by the installed Gemini CLI.
