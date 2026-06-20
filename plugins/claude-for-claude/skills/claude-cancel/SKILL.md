---
name: claude-cancel
description: Cancel a tracked Claude for Claude background job when the runtime can safely validate it.
---

# Claude Cancel

Use this skill when Claude Code needs to cancel a tracked Claude for Claude job.

Run:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" cancel
```

Rules:
- Require a job id.
- Do not claim a running process was stopped unless the runtime reports `cancelled`.
- If the runtime reports `cancel_failed`, tell the user that the plugin could not validate a process identity for safe cancellation.
