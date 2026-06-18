---
name: antigravity-status
description: List Antigravity for Claude background jobs and inspect their current status.
---

# Antigravity Status

Use this skill when Claude Code needs to list Antigravity background jobs or check whether a queued job has finished.

Run:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs" jobs
```

For one job:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs" status "$JOB_ID"
```
