# Changelog

## 0.1.1

- Fix `parseClaudeJson` to treat `is_error`/non-success `subtype`/`api_error_status` payloads as failures instead of emitting an API error string as a successful review/plan.
- Fix `/claude:roles` slash command (and bare `roles`) to default to `roles list` instead of printing only usage.
- Redact quoted/JSON secret values in `sanitize` (including embedded escaped quotes) so `"password":"..."` is masked.
- Forward `stop_hook_active` to the Stop review gate via a non-blocking stdin read so the loop-guard works.
- Classify Claude CLI provider failures from stdout (auth/quota/overload) instead of bucketing them as `unknown`.
- Correct `assisted-review`/`setup` argument-hints to match the real flags; make the resource governor and corrupt round-summary reads degrade instead of crashing.
- Make the reserved-job claim lock atomic via a per-claim ownership token (no double-claim).

## 0.1.0

- Added the initial Claude for Claude marketplace plugin.
- Added isolated `claude -p` read-only review, planning, multi-review, scorecards, tracked jobs, GitHub Actions template generation, and opt-in Stop review gate support.
- Added child-process recursion guard through `CLAUDE_FOR_CLAUDE_CHILD=1`.
