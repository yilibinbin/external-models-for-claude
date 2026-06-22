# Codex for Claude

Use OpenAI Codex from Claude Code for code review, adversarial review, rescue, and delegated implementation tasks.

Install from this marketplace:

```bash
claude plugin marketplace add yilibinbin/external-models-for-claude --scope user
claude plugin install codex@external-models-for-claude --scope user
```

The `codex` plugin in this marketplace is a local Apache-2.0 extension of the OpenAI-authored Codex Claude Code plugin files bundled under `plugins/codex`. OpenAI attribution, `LICENSE`, and `NOTICE` are preserved; local extensions are documented in `plugins/codex/FORK_NOTICE.md` without asserting unverified upstream lineage.

This plugin keeps Codex as the only provider. It does not route requests to Gemini, Antigravity, or Claude providers.

## Extended Commands

- `/codex:doctor` checks local readiness without running a model request.
- `/codex:github-actions render|init|validate` creates a safe pull-request review workflow template. In this release it remains preview/advisory until release-host Codex CLI version and stdin auth contracts are verified.
- `/codex:multi-review` runs focused Codex read-only review passes using role packs.
- `/codex:setup` can enable the optional Stop review gate.

## Quality Presets

`--quality fast|standard|strong|max` is Codex-native. It never selects Gemini, Antigravity, or Claude models. It changes Codex `turn/start` reasoning effort only for `task`, `adversarial-review`, and `multi-review`.

For native `/codex:review`, `--quality` has zero runtime effect because the current `runAppServerReview` helper does not accept an effort field. It only labels the tracked-job summary so humans can see which preset was requested.

## Strict Parser Boundary

Unknown flags on `/codex:review`, `/codex:adversarial-review`, and `/codex:task` are rejected instead of being treated as prompt text. If prompt or focus text must intentionally begin with a flag-like token, put `--` before that text so the companion treats the remaining tokens as positionals.

This is a strict-parser migration from earlier permissive behavior. `/codex:task` is prompt-first: unknown option-like tokens before the first prompt token still fail, so write `/codex:task -- --foo is broken` when the prompt begins with a flag-like token. After the first prompt token, flag-like text is preserved, so `/codex:task fix the --foo bug` remains valid prompt text.

This strict flag behavior applies to setup, the new deterministic commands, and review/task model-entry commands. It does not claim to change legacy status/result/cancel parser behavior in this release.

## Capacity

`/codex:multi-review` uses one `model-call` lease for the full sequential role run. Each role is still a separate sequential Codex turn, so the default five-role pack can issue five Codex turns under that one slot. If you set `CODEX_FOR_CLAUDE_GLOBAL_MAX_MODEL_CALLS=1`, that command can block other foreground review commands until every role completes.

The default global `model-call` limit is 2, which lets one multi-review and one foreground model command run together, but two concurrent model-call commands, or one `multi-review` plus one long task, can still saturate the pool and make the next foreground review or task return `capacity_blocked` until a slot is released. Stop-gate review uses the independent `stop-gate` pool, controlled by `CODEX_FOR_CLAUDE_GLOBAL_MAX_STOP_GATES` and defaulting to `1`.

## Stop Review Gate

`/codex:setup` keeps the optional Stop review gate fail-closed by default for tool, auth, timeout, capacity, and invalid-output failures. Set `stopReviewGateFailOpen` only when editor availability is preferred over strict Stop gating.
