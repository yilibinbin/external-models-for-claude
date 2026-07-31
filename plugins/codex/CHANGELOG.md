# Changelog

## 1.1.0-fh.7

- Carry the app-server's exit reason across the broker as structured data. `review/start`/`turn/start` are streaming, so once the request has returned there is no pending call left to reject and the broker previously just closed its sockets — the outer client then reported only "connection closed", with not even the exit code. The reason now travels as `{code}`/`{signal}` on a `broker/appServerExited` notification, validated on receipt and rendered from a local template.
- Deliberately does **not** quote the child's stderr. That was implemented and withdrawn: stderr is unbounded and not authored by this plugin, so no redaction pass can bound what it may contain. Four rounds of pattern-patching still leaked `DATABASE_URL`, `PRIVATE_KEY` and `SESSION_COOKIE`, and the patterns added to catch `_`-delimited names backtracked quadratically — 3.9 s on a 40 KB dump, run synchronously inside the exit handler, stalling the very rejection the feature was meant to deliver. `sanitize.mjs` is reverted to its previous form, which removes that cost entirely (40 KB: 3946 ms → 1 ms).
- Release the child's stdio in `close()`. These pipes stay open while any descendant holds the inherited descriptor, and an open pipe pins this process's event loop: measured, a parent listening on stderr exits in 60 ms normally and never exits once a grandchild inherits it. This is a pre-existing hang — the same accumulator with no release exists in the prior version — and the release is unconditional so it covers a clean exit too.

## 1.1.0-fh.6

- Adopt upstream `db52e28`: pin `shell: false` on the `git()`/`gitChecked()` wrappers and let `runCommand` honour `options.shell`. `detectDefaultBranch` returns whatever `refs/remotes/origin/HEAD` points at, unvalidated, and that string reaches git argv at `["merge-base", "HEAD", baseRef]`; on Windows the spawn interposed a shell, and `git check-ref-format` bans spaces but not `&`, `|`, backticks or `$()`, so a cloned repository's default branch name was a command injection there. Unreachable on darwin/linux, where the platform ternary already evaluated to `false`. The opt-in shape is deliberate: `runCommand` also spawns the `npm`/`codex` `.cmd` shims, which Windows cannot launch without a shell.
- Not adopted from upstream v1.0.5/v1.0.6: the `/codex:transfer` command. The capability ships natively in codex-cli, upstream's own plugin is separately installable for it, and porting would violate four of this fork's command-surface invariants and bypass the resource governor.

## 1.1.0-fh.5

- Stop pinning the marketplace's `metadata.version` inside this plugin. The constant existed only to be compared against `marketplace.json`, so the check was circular, and its real effect was that **every** marketplace bump edited a file inside `plugins/codex` while `CODEX_VERSION` stayed put — shipping changed codex bytes under an unchanged version key, which a version-pinned install never picks up. Three merged PRs (#7, #8, #9) drifted this way. The marketplace version is now asserted only in `tests/`, which ships in no plugin, and `tests/test_plugin_version_pinning.py` guards the drift class repo-wide.

## 1.1.0-fh.4

- Route `--quality max` to the current model's TRUE strongest reasoning tier (including `max`/`ultra`) instead of a hardcoded `high`, resolved per-model at session time from the app-server `model/list` capability table (`isDefault` model when `--model` is omitted).
- Replace the global `VALID_REASONING_EFFORTS` whitelist with per-model capability validation: `--effort` is now checked against the current model's real `supportedReasoningEfforts`. **Behavior change:** an `--effort` value that the global whitelist previously let through, but that the resolved model does not actually support (e.g. `--effort xhigh` on a model whose ceiling is `high`), now fails loud within the session instead of being silently forwarded to the app-server. This is the intended capability verification, not a regression, but it can turn a command that previously "ran" into a hard error.
- Degrade safely when `model/list` is unavailable: omit the reasoning-effort for all models and warn (run at the app-server default tier) rather than guessing a tier or failing the run.
- Declare the `model/list` method in the app-server protocol contract; native `review` stays metadata-only (no effort channel), unaffected by this change.

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
