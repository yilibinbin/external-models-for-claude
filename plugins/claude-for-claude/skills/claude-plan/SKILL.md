---
name: claude-plan
description: Ask Claude CLI for an independent implementation plan that Claude Code can reconcile before editing.
---

# Claude Plan

Use this skill before substantial implementation work when a second model's decomposition could expose missed tests, hidden constraints, or a safer order of operations.

Run:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" plan
```

Rules:
- Treat Claude's plan as a competing design artifact, not an authority.
- Reconcile Claude's plan with Claude Code's local repo evidence before editing.
- Keep the final Claude Code plan in local planning files when the task uses file-backed planning.
- Do not let Claude's plan override explicit user instructions.

Output usage:
- Extract observed facts.
- Compare task order against Claude Code's task plan.
- Add missing tests or risk checks when Claude found real gaps.
- Reject unsupported suggestions with a short reason.
