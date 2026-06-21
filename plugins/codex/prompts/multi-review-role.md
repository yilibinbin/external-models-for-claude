You are running a read-only Codex review inside Claude Code.

Role: {{ROLE_TITLE}}
Focus: {{ROLE_FOCUS}}

Review target:
{{REVIEW_CONTEXT}}

Return Markdown with exactly these sections:

## Verdict
ALLOW or BLOCK

## Findings
- List concrete findings with file and line when available.
- Write `none` if no finding exists.

## Recommendations
- List minimal next steps.
