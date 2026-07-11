# Changelog

## 1.1.0-fh.3

- Reject the pending turn when the `codex app-server` transport dies mid-turn (crash/OOM/socket drop) instead of hanging `review`/`task` forever, and self-terminate the shared broker when its backing app-server child dies so a stale "ready" broker is not reused.
- Reclaim a corrupt/0-byte `.governor.lock` (from a crash mid-write) instead of deadlocking the resource-governor mutex; guard the job heartbeat so a corrupt sidecar cannot crash the detached worker.
- Verify broker PID liveness and identity before terminating its process group on `SessionEnd` (avoids killing an unrelated recycled-PID process group).
- Harden the `cancel`, `status`, and `result` slash commands against `$ARGUMENTS` shell injection (argv-token pattern, matching the other commands).
- Normalize the model alias on `review`/`adversarial-review` (so `-m spark` resolves consistently), prefer an exact plugin-ID match in install-consistency, honor `CLAUDE_PROJECT_DIR` in the malformed-stdin fail-closed path, reject self-contradictory version-axis evidence, do a full-buffer binary scan and fence/control-char neutralization for inlined untracked files, never evict an active job in state pruning (with private payload stripped), validate the CI workflow before `github-actions init` writes it, and sanitize the persisted job summary and markdown table cells (secrets/paths/control chars).

## 1.1.0-fh.2

- Tear down the spawned child/socket when `app-server` `initialize()` times out, and bound `close()` so a wedged child that ignores SIGTERM cannot hang it (escalates to SIGKILL/`terminateProcessTree`/`socket.destroy`).
- Add a bounded `initialize`/request timeout so a wedged `codex app-server` fails fast instead of hanging review/task/status.
- Fail-safe the SessionEnd/SessionStart lifecycle hook on malformed stdin; bound `sendBrokerShutdown` with a socket timeout; set an explicit `maxBuffer` on the Stop-gate review subprocess; terminate an orphaned worker when a background lease transfer fails; surface the login next-step when the auth probe fails.

## 1.1.0-fh.1

- Add local marketplace extension notice while preserving OpenAI attribution.
- Prepare Codex-native maturity improvements for release checks, diagnostics, capacity governance, hardened jobs, preview CI workflow rendering, multi-role review, quality presets, and safer stop gates.
- Breaking: the `task` subcommand (used by `/codex:rescue`), `/codex:review`, and `/codex:adversarial-review` now reject unknown flag-like tokens before the first positional; use `--` before prompt/focus text that intentionally starts with `-` or `--`.
- Add `/codex:doctor` readiness checks that do not issue a model request.
- Add `/codex:multi-review` for focused read-only role-pack review passes. A multi-review run holds one `model-call` capacity slot for the whole sequential role run; the default five-role pack can still issue five sequential Codex turns. Stop-gate review uses a separate `stop-gate` capacity slot.
- Add Codex-native `--quality fast|standard|strong|max` presets for task, adversarial-review, and multi-review reasoning effort. Native `/codex:review` records only a visible job-summary label and has zero runtime effect.
- Harden the optional Stop review gate so tool, auth, timeout, capacity, and invalid-output failures fail closed by default. Set `stopReviewGateFailOpen` only when editor availability is preferred over strict Stop gating.
- Ship `/codex:github-actions render|init|validate` as preview/advisory workflow tooling. The generated workflow is not advertised as ready until release-host Codex CLI version and stdin auth contracts are verified.
- Known limitation: background-job lease cleanup is daemonless and can temporarily treat a quickly reused dead pid as alive until later job-state or lease expiry evidence corrects it.
- Note: this changelog entry covers only the local extension work in this release and does not invent historical notes for earlier bundled versions.

## 1.0.0

- Initial version of the Codex plugin for Claude Code
