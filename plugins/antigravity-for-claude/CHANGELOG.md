# Changelog

## 0.1.3 - 2026-07-22

- `doctor` (both text and `--json`) now says so when the selected model is absent from the catalog `agy models` reported, instead of printing `Ready: yes` and letting an unusable `--model` value surface later as an empty review. Reported only, never gated: the catalog reports slugs and `--model` takes display names, so a hard gate would fail every run.
- Stop selecting a model `agy` will refuse. `agy models` reports slugs (`gemini-3.1-pro-high`) while `agy --model` takes the display names this plugin curates (`Gemini 3.1 Pro (High)`) and rejects those slugs outright, so the curated default never matched a catalog entry and selection fell through to the catalog's *first* entry — `gemini-3.6-flash-high`, which `agy` then rejected with `invalid model selection`, failing every headless review with an empty result. Both providers were affected (gemini picked `gemini-3.6-flash-high`, claude picked `claude-sonnet-4-6`). A catalog entry is now used only when it confirms the curated default verbatim; otherwise the default stands.

## 0.1.2 - 2026-07-11

- Fix a resource-governor deadlock: a corrupt or 0-byte `.governor.lock` is now reclaimed as stale (`!lock || mtime-expired || dead-pid`) instead of blocking every review for the full wait; the lock is written and fsynced before `acquireMutex` returns so a crash cannot leave a 0-byte lock.
- Stop classing large-but-valid `agy` output as a transient failure: `ENOBUFS`/maxBuffer overflow is no longer retried (previously re-ran the model up to 16×) and reports "agy output exceeded the 20 MB buffer"; the async print path now shares the same 20 MB stdout+stderr cap as the sync path.
- Harden the GitHub Actions fork-safety gate: `extractRunBlocks` now also inspects inline (`run: echo …`) and folded (`run: >`) and compact `- run:` steps, closing an `${{ github.* }}` injection bypass that a mixed block/inline workflow could slip through.
- `extractJsonObject` now prefers a schema-valid `json` block over the first fenced block, so a stray code fence in model prose no longer preempts the real structured review.
- Honour `ANTIGRAVITY_FOR_CLAUDE_MODEL_PROVIDER=claude` (was silently downgraded to gemini); `doctor` and the GitHub-actions options path read the env too.
- Reject unknown/mistyped dash-prefixed flags in `review` instead of folding them into the model focus text (parity with `parseDoctorArgs`); honours `--`.
- Sanitise raw model output (secrets, local paths, control chars) before it is displayed, persisted to job JSON, or used as the Stop-gate reason; mailbox message bodies are sanitised too.
- Tolerate corrupt job/mailbox JSON (return null / skip rather than throwing), distinguish a lock-acquire timeout from a missing job, and fsync-before-rename with orphaned-`.tmp` cleanup in the atomic JSON writers.
- Add `--background`/`--wait` (and github-actions `--timeout-minutes`) to the affected command argument-hint frontmatter.

## 0.1.1 - 2026-06-23

- Honour `stop_hook_active` in the Antigravity Stop review gate via a non-blocking stdin read and a `runReviewGate` loop-guard short-circuit (parity with claude-for-claude).
- Align `review` argument-hint with the parser (drop the unimplemented `--wait`); map the session-lifecycle event explicitly instead of silently defaulting to `start`.
- Document all 16 shipped skills in `skills/README.md`.

## 0.1.0 - 2026-06-14

- Add normalized scorecard review contracts for `review`, plugin-managed `multi-review`, `adversarial-review`, and `plan-review`.
- Add `plan --taskset`, `plan-review`, and bounded advisory `assisted-review` quality-loop commands.
- Add workspace-bound plan-file reading, repo-external taskset state, validation-evidence blocks, project-instruction advisory context, and round summary indexes.
- Harden `agy` script-wrapper execution by resolving POSIX shebang scripts through their interpreters before spawning.
- Add quality-loop skills, natural-language routing guards, release-check guards, and fake-CLI regression tests.

## 0.6.1 - 2026-06-13

- Add a file-backed global resource governor for foreground reviews, Stop gates, multi-review fan-out, background jobs, and reserved workers.
- Add bounded spawn retry handling for transient local process pressure (`EAGAIN`, `EMFILE`, `ENFILE`, `ENOBUFS`), including POSIX supervisor retry for inner `agy` startup pressure.
- Add release-check and pytest coverage for resource-governor and spawn-retry safety.

## 0.6.0 - 2026-06-12

- Added agy-native capability, model catalog, and outcome classification modules.
- Added cheap `doctor` diagnostics for local `agy`, model catalog, provider policy, and hook compatibility.
- Hardened background job lifecycle with bounded worktree fingerprints, idempotency keys, heartbeats, and safer unread-result handling.
- Added bounded process probe diagnostics for cancellation and lifecycle decisions.
- Added release-check guards to prevent Claude-native/Fable/SDK behavior from leaking into Antigravity.

## 0.5.4 - 2026-06-09

- Resolve generated GitHub Actions workflows through the installed Antigravity plugin root instead of repo-relative runtime paths.
- Allow `release-check` to run from an installed plugin cache where repository-level README/docs files are absent.
- Add release guards for installed-plugin release checks and workflow plugin-root resolution.

## 0.5.3 - 2026-06-08

- Reframe Antigravity skills around natural-language model routing so users can ask for review, planning, rescue, and Claude-through-Antigravity without writing internal CLI flags.
- Add release-check and pytest guards that preserve Gemini-default provider behavior, explicit Claude-through-Antigravity selection, and rejection of GPT/OpenAI model labels.
- Keep existing `agy` invocation, model validation, hooks, workflows, and safety boundaries unchanged.

## 0.5.2 - 2026-06-08

- Replace the Antigravity plugin logo and composer icon with a dual-tile Antigravity + Claude Code joint-brand design.
- Keep existing `agy` behavior, model-provider selection, hooks, workflows, release checks, and safety boundaries unchanged.

## 0.5.1 - 2026-06-08

- Refresh the Antigravity plugin logo and composer icon using the official Antigravity app arch mark as the base visual element.
- Keep existing `agy` behavior, model-provider selection, hooks, workflows, release checks, and safety boundaries unchanged.

## 0.5.0 - 2026-06-08

- Promote Antigravity for Claude to the mature plugin-managed workflow surface: structured review output, sanitized reports, role packs, background jobs, status/result/cancel, mailbox, leases, lifecycle hooks, GitHub Actions workflow rendering and validation, release checks, and opt-in real smoke.
- Document the explicit boundary that Antigravity for Claude uses `agy` only and does not claim Claude SDK, Gemini native-agent, or ultrareview parity.
- Clarify that Claude-through-Antigravity is available only through explicit Antigravity provider selection.
- Document that CI review workflows require an authenticated `agy` command and that real smoke remains opt-in.
- Versions 0.2.0 through 0.4.0 were internal pre-release iterations and were not published as standalone marketplace releases.

## 0.1.0 - 2026-06-07

- Initial Antigravity for Claude plugin.
- Document the local Antigravity CLI (`agy`) requirement and supported discovery through `agy`, `AGY_CLI_PATH`, or `ANTIGRAVITY_CLI_PATH`.
- Add explicit Gemini/Claude model-provider switching, including Claude-through-Antigravity model selection.
- Reject GPT/OpenAI model labels as unsupported for this plugin.
- Cover the initial command surface: `setup`, `capabilities`, `review`, `adversarial-review`, `multi-review`, `plan`, `rescue`, `review-gate`, `real-smoke`, and `release-check`.
