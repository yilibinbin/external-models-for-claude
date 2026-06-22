---
name: claude-collaboration-loop
description: "Run a full Claude Code-Claude collaboration workflow: Claude Code plans, Claude plans, Claude Code reconciles, Claude Code implements, Claude reviews, Claude Code reports."
---

# Claude Collaboration Loop

Use this skill for complex, high-stakes, or ambiguous tasks where Claude Code and Claude should cover each other's blind spots.

Workflow:
1. Claude Code reads repo state and writes or updates `task_plan.md`, `findings.md`, and `progress.md` when file-backed planning applies.
2. Claude Code runs:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" plan
```

3. Claude Code reconciles Claude's plan against local evidence:
   - adopt concrete missing tests,
   - adopt safer task ordering when justified,
   - reject unsupported speculation,
   - record the reconciliation in `findings.md`.
4. Claude Code implements the reconciled plan.
5. Claude Code runs:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" adversarial-review
```

6. Claude Code reports:
   - implemented files,
   - verification commands,
   - Claude findings adopted,
   - Claude findings rejected,
   - residual risk.

Hard boundaries:
- Claude review output is not self-executing.
- Claude Code must not claim a Claude finding is fixed unless it applied and verified the fix.
- If Claude CLI is unavailable, fall back to a Claude Code-only workflow and report that the cross-model pass was skipped.
