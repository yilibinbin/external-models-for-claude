# Changelog

## 1.1.0-fh.1

- Add local marketplace extension notice while preserving OpenAI attribution.
- Prepare Codex-native maturity improvements for release checks, diagnostics, capacity governance, hardened jobs, preview CI workflow rendering, multi-role review, quality presets, and safer stop gates.
- Breaking: `/codex:task`, `/codex:review`, and `/codex:adversarial-review` now reject unknown flag-like tokens before the first positional; use `--` before prompt/focus text that intentionally starts with `-` or `--`.
- Add `/codex:doctor` readiness checks that do not issue a model request.
- Add `/codex:multi-review` for focused read-only role-pack review passes. A multi-review run holds one `model-call` capacity slot for the whole sequential role run; the default five-role pack can still issue five sequential Codex turns. Stop-gate review uses a separate `stop-gate` capacity slot.
- Add Codex-native `--quality fast|standard|strong|max` presets for task, adversarial-review, and multi-review reasoning effort. Native `/codex:review` records only a visible job-summary label and has zero runtime effect.
- Harden the optional Stop review gate so tool, auth, timeout, capacity, and invalid-output failures fail closed by default. Set `stopReviewGateFailOpen` only when editor availability is preferred over strict Stop gating.
- Ship `/codex:github-actions render|init|validate` as preview/advisory workflow tooling. The generated workflow is not advertised as ready until release-host Codex CLI version and stdin auth contracts are verified.
- Known limitation: background-job lease cleanup is daemonless and can temporarily treat a quickly reused dead pid as alive until later job-state or lease expiry evidence corrects it.
- Note: this changelog entry covers only the local extension work in this release and does not invent historical notes for earlier bundled versions.

## 1.0.0

- Initial version of the Codex plugin for Claude Code
