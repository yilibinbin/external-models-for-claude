# Changelog

## 0.1.4 - 2026-08-05

A serial-panel sweep of this plugin (never previously reviewed by it, unlike
the sibling codex plugin) found and closed defects across five review
rounds — Claude found the first set, Gemini's review of that diff found a
JSON-corruption bug in the fix itself, Codex's review of the corrected diff
found a critical regression the corruption fix had introduced plus a second
gap the corruption fix's own redesign had opened, Codex's own
re-verification pass of THAT fix found the shell hardening was still
overrideable by a caller plus two more redaction gaps (quoted assigned
values, composite values under a sensitive key), a further Codex
re-verification pass found an unterminated-quote redaction gap, and
CodeRabbit's independent review of the whole diff found a prototype-
pollution path and a permission check that didn't actually verify anything.
Documented here because most of these were caught only by the later panel
stages, not by the person who wrote the code:

- **Structured review output bypassed redaction entirely.** The `--json`,
  `--structured`, `--scorecard`, and `plan --taskset` branches of `review`
  wrote the raw, parsed model JSON straight to stdout with zero sanitization
  — not even the (also-hardened, see below) weak regex — while the plain-text
  branch two branches below called `sanitizeModelText`. A finding whose
  `evidence` field quoted a real hardcoded credential printed it verbatim,
  and for `--background` jobs persisted it unredacted to the on-disk job
  file.
- **The first fix for that (sanitizing raw stdout text before parsing it as
  JSON) could corrupt the JSON.** Gemini's review found that a redacted span
  can consume the backslash escaping a quote inside a JSON string value,
  turning `\"` into a bare `"` that prematurely terminates the string —
  breaking `JSON.parse` for otherwise-valid model output. Fixed by parsing
  first and sanitizing only the decoded string values (`deepSanitizeStrings`
  in `lib/sanitize.mjs`), applied to the taskset/scorecard/`--json`/
  `--structured` branches and to `finishJob`'s job-state persistence (made
  JSON-aware with a safe fallback to whole-text sanitization for non-JSON
  output).
- **That fix in turn discarded the JSON key name before sanitizing the
  value**, so `{"password": "hunter2"}` passed through untouched — the value
  alone has no distinctive shape and no embedded `key=value` text for the
  regex to match, and the key context that would have flagged it was thrown
  away during the walk. Codex's review of the corrected diff found this by
  probing the helper directly. `deepSanitizeStrings` now checks the key name
  too and replaces the whole value when the key itself is sensitive,
  independent of the value's own shape.
- **The secret regex missed compound key names and URI credentials.**
  `AWS_SECRET_ACCESS_KEY=...`, `STRIPE_SECRET_KEY: ...`, and
  `DATABASE_URL=postgres://user:pass@host` all passed through untouched,
  because the old pattern required its keyword immediately adjacent to `:`/`=`.
  Replaced with segment-based key matching (ported from the hardened codex
  sanitizer) plus a URI-with-inline-credentials pattern, while keeping every
  original keyword shape (`api_key`, `API-Key`, `ApiKey`, `token`, `secret`,
  `password`) working and not newly flagging ordinary compounds like
  `token_count`.
- **The Stop review gate failed open on every failure path**, with no way to
  opt into stricter behavior — untrusted git context, a timeout, a non-zero
  model exit, or invalid model output all silently let the stop proceed,
  unlike the sibling codex plugin's `stopReviewGateFailOpen` (default false).
  Now fails closed by default; set
  `ANTIGRAVITY_FOR_CLAUDE_REVIEW_GATE_FAIL_OPEN=on` to restore the previous
  always-allow behavior.
- Mailbox directory and thread files were created with Node's default modes
  (0755/0644 under a typical umask) instead of the 0700/0600 used by every
  sibling state writer in the same lib directory.
- **A Windows fix for the item below shipped a worse bug than it closed.**
  `agy` invocations had no explicit `shell` option, and the first attempt at
  fixing that copied the sibling codex plugin's `process.mjs` win32 default
  of `shell:true` (reasoning that `agy.cmd` needs a shell to run). Codex's
  review flagged this as critical: with `shell:true`, Node does not escape
  command+args, and this call carries the full prompt — including
  working-tree diff content — as a single argument, so shell metacharacters
  in reviewed repository content would be interpreted by `cmd.exe`. Codex's
  own `process.mjs` is safe with `shell:true` only because that default is
  reserved for trusted, fixed-argv calls; its own `git.mjs` explicitly opts
  back to `shell:false` for every call carrying repository-derived arguments,
  which is what this call needed too. Corrected to `shell:false` always —
  `.cmd`/`.bat` execution still works via Node's own internal, escaped
  handling for those extensions, independent of the `shell` option. That
  first correction was itself still `options.shell ?? false`, which let a
  caller override the hardening by passing `{shell: true}`; Codex's
  re-verification pass of the fix caught that both exported functions accept
  an arbitrary options object, so this was reachable, not just defensive
  paranoia. Corrected again to a literal `shell: false`, not derived from
  options at all.
  A further re-verification pass raised, but this release does NOT act on,
  a claim that literal `shell:false` itself breaks `agy.cmd` execution on
  Windows (`.cmd` files supposedly requiring `shell:true` to run at all).
  This is not new: the code before this entire round of fixes never set an
  explicit `shell` option either, which is functionally identical to
  `shell:false`, so if the claim were true it would be a pre-existing
  platform issue, not something introduced here — and it contradicts the
  well-established Node/libuv behavior the rest of the Windows npm ecosystem
  depends on (spawning a `.cmd`-shimmed CLI without `shell:true` is the
  standard, working pattern), which CVE-2024-27980 itself is evidence for:
  the CVE was about improper *escaping* in that automatic `.cmd`-handling
  path, which presupposes the automatic handling exists. Neither this nor
  the reviewer's claim has been verified against a real Windows machine —
  flagged here rather than silently resolved either way.
- `redactAssignedValues`' value reader could not start a match on a quote
  character, so a quoted assignment — `password: "hunter2"`,
  `password='hunter2'` — fell through unredacted even though the bare form
  (`password=hunter2`) was already caught; a common config/log/YAML shape,
  reachable through every remaining raw-text `sanitizeModelText` call site
  (mailbox bodies, the plain-text review branch, the Stop-gate reason,
  validation-evidence summaries). Ported an escape-aware quoted-value pattern
  from the codex sanitizer, tried before the bare fallback — and, caught by a
  second re-verification pass, an UNTERMINATED quoted value (`password="hunter2`,
  the shape a truncated model response produces) matched neither the quoted
  nor the bare rule and leaked the credential completely; now fails closed on
  the remainder when a value opens with a quote that never closes, mirroring
  the codex sanitizer's own rule for the identical case.
- The key-aware `deepSanitizeStrings` fix above checked key sensitivity only
  inside its string branch, so a sensitive key whose value was an object or
  array was traversed instead of replaced wholesale —
  `{password: {value: "hunter2"}}` recursed into the inner object with the
  keyHint reset to the non-sensitive inner key "value", losing the
  "password" context one level down. The check now runs before type
  dispatch and short-circuits, replacing any string/object/array under a
  sensitive key outright; numbers and booleans under a sensitive key
  (a `token_expires_in` duration) are deliberately left alone, since they
  cannot carry secret-shaped text.
- **`deepSanitizeStrings` was reachable for prototype pollution.** It rebuilt
  each object with `out[key] = ...`; for a parsed-JSON key literally named
  `"__proto__"`, plain bracket assignment on an ordinary `{}` triggers
  `Object.prototype`'s `__proto__` accessor setter instead of creating a
  literal property, silently reassigning the RESULT object's own prototype
  to whatever (sanitized) value that key held — reachable from untrusted
  model JSON, which is exactly this function's input. Found by CodeRabbit's
  review of the whole diff. Rebuilt with `Object.defineProperty` instead,
  which always creates a literal own data property regardless of the key's
  name.
- **The mailbox permission fix (above) didn't verify it actually worked.**
  `chmodSync`'s failure was caught and silently ignored, and the directory
  was still returned and used either way — so a pre-existing mailbox
  directory that could NOT be corrected back to 0700 (e.g. owned by a
  different identity) would silently persist free-text message content,
  sanitized only by this plugin's own regex-based redaction, into a
  directory this code could not confirm was owner-only. Found by CodeRabbit.
  Now verifies the actual on-disk mode via `statSync` after the best-effort
  `chmodSync` and throws, naming the expected mode, rather than trusting the
  chmod call succeeded. POSIX only (Windows mode bits are not meaningful).
- `plan --taskset` reported `ok:true`/exit 0 for a degenerate model response
  with zero subtasks, indistinguishable from a real successful plan to any
  caller gating on exit code alone. `saveTaskset` now rejects it.

CodeRabbit also raised, independently of Codex, that the Windows
`shell:false` + `agy.cmd` combination above may not work as intended and
suggested resolving the CLI to a native executable or rejecting `.cmd`/`.bat`
targets during preflight. This is NOT acted on in this release: doing so
would trade an unverified claim for a confirmed regression (blocking the
standard `npm install -g` Windows setup entirely) if the claim turns out to
be wrong, and the claim itself contradicts well-established Node/libuv
behavior the wider Windows npm ecosystem depends on (spawning a
`.cmd`-shimmed CLI without `shell:true` is the standard, working pattern) —
CVE-2024-27980, which both reviewers' concern is downstream of, is itself
evidence that Node's automatic `.cmd` handling exists (there is nothing to
mis-escape in an automatic wrap that does not happen). Flagged here for a
maintainer with access to a real Windows machine to settle definitively,
rather than resolved by further unverified reasoning from either side.

## 0.1.3 - 2026-07-22

- Stop selecting a model `agy` will refuse. `agy models` reports slugs (`gemini-3.1-pro-high`) while `agy --model` takes the display names this plugin curates (`Gemini 3.1 Pro (High)`) and rejects those slugs outright, so the curated default never matched a catalog entry and selection fell through to the catalog's *first* entry — `gemini-3.6-flash-high`, which `agy` then rejected with `invalid model selection`, failing every headless review with an empty result. Both providers were affected (gemini picked `gemini-3.6-flash-high`, claude picked `claude-sonnet-4-6`). A catalog entry is now used only when it confirms the curated default verbatim; otherwise the default stands.
- If a future `agy` retires a curated default, set `ANTIGRAVITY_FOR_CLAUDE_GEMINI_MODEL` or `ANTIGRAVITY_FOR_CLAUDE_CLAUDE_MODEL` to a model it accepts; those overrides take priority over both the catalog and the default. The catalog cannot be used to pick a replacement automatically, because catalog membership does not indicate that `agy --model` will accept the value (it currently indicates the opposite).

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
