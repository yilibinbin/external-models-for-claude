---
name: gemini-result
description: Retrieve a tracked Gemini for Claude job result by job id.
---

# Gemini Result

Use this skill when Claude Code needs to fetch the stored output for a Gemini for Claude background job.

Run:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/gemini-companion.mjs" result
```

Rules:
- Require a job id from the user or from a previous `gemini-status`/`jobs` output.
- Preserve the job status, result text, and any recorded failure diagnostics.
- If the job is not found, report that no tracked job exists for that id in the current workspace.
