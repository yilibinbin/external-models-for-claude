---
name: gemini-collaboration-loop
description: "Run a full Claude Code-Gemini collaboration workflow: Claude Code plans, Gemini plans, Claude Code reconciles, Claude Code implements, Gemini reviews, Claude Code reports."
---

# Gemini Collaboration Loop

Use this skill for complex, high-stakes, or ambiguous tasks where Claude Code and Gemini should cover each other's blind spots.

Workflow:
1. Claude Code reads repo state and writes or updates `task_plan.md`, `findings.md`, and `progress.md` when file-backed planning applies.
2. Claude Code runs:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/gemini-companion.mjs" plan
```

3. Claude Code reconciles Gemini's plan against local evidence:
   - adopt concrete missing tests,
   - adopt safer task ordering when justified,
   - reject unsupported speculation,
   - record the reconciliation in `findings.md`.
4. Claude Code implements the reconciled plan.
5. Claude Code runs:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/gemini-companion.mjs" adversarial-review
```

6. Claude Code reports:
   - implemented files,
   - verification commands,
   - Gemini findings adopted,
   - Gemini findings rejected,
   - residual risk.

Hard boundaries:
- Gemini review output is not self-executing.
- Claude Code must not claim a Gemini finding is fixed unless it applied and verified the fix.
- If Gemini CLI is unavailable, fall back to a Claude Code-only workflow and report that the cross-model pass was skipped.
