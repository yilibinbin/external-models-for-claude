# External Models for Claude

`external-models-for-claude` is a Claude Code marketplace for multi-model development workflows.

## Included Plugins

- `codex`: OpenAI's official Claude Code plugin for Codex review and delegation.
- `gemini-for-claude`: Gemini CLI review, planning, scorecards, role packs, tracked jobs, GitHub Actions workflow rendering, and opt-in stop gates.
- `antigravity-for-claude`: Antigravity CLI review, planning, scorecards, tracked jobs, GitHub Actions workflow rendering, and explicit Gemini/Claude provider selection.

## Installation

```bash
claude plugin marketplace add yilibinbin/external-models-for-claude --scope user
claude plugin install codex@external-models-for-claude --scope user
claude plugin install gemini-for-claude@external-models-for-claude --scope user
claude plugin install antigravity-for-claude@external-models-for-claude --scope user
```

Reload Claude Code plugins after installing.

## Codex for Claude

The `codex` plugin in this marketplace is a local Apache-2.0 extension of the OpenAI-authored Codex Claude Code plugin files bundled under `plugins/codex`. OpenAI attribution, `LICENSE`, and `NOTICE` are preserved; local extensions are documented in `plugins/codex/FORK_NOTICE.md` without asserting unverified upstream lineage.

### Extended Commands

- `/codex:doctor` checks local readiness without running a model request.
- `/codex:github-actions render|init|validate` creates a safe pull-request review workflow template. In this release it remains preview/advisory until release-host Codex CLI version and stdin auth contracts are verified.
- `/codex:multi-review` runs focused Codex read-only review passes using role packs.
- `/codex:multi-review` holds one model-call capacity slot for the entire sequential role run. Each role is still a separate sequential Codex turn, so the default five-role pack can issue five Codex turns under that one slot. With model-call limit `1`, it can block normal foreground review commands. With the default limit `2`, one multi-review normally leaves one slot, but two concurrent model-call commands can saturate the pool and make a third foreground review return `capacity_blocked`. Stop-gate review uses a separate `stop-gate` capacity slot.
- `--quality fast|standard|strong|max` is Codex-native and affects task, adversarial-review, and multi-review reasoning effort. Native `/codex:review` records only the visible job-summary label and has zero runtime effect.
- Unknown flags on review/task commands are rejected. Use `--` before prompt or focus text that intentionally starts with flag-like tokens.
- `/codex:setup` keeps the optional Stop review gate fail-closed by default for tool, auth, timeout, capacity, and invalid-output failures. Set `stopReviewGateFailOpen` only when editor availability is preferred over strict Stop gating.

## Provider Setup

Run the setup command for the plugin you install:

```bash
/codex:setup
/gemini-for-claude:setup
/antigravity-for-claude:setup
```

For Antigravity provider selection:

```bash
/antigravity-for-claude:review --model-provider gemini
/antigravity-for-claude:review --model-provider claude
```

The default provider can also be configured through the plugin's setup/status flow or the relevant environment variable documented by the plugin.

## Validation

Before release, this repository is expected to pass:

```bash
claude plugin validate --strict .claude-plugin/marketplace.json
claude plugin validate --strict plugins/codex
claude plugin validate --strict plugins/gemini-for-claude
claude plugin validate --strict plugins/antigravity-for-claude
python3 -m pytest -q
```

Live provider smoke tests are opt-in because they consume provider quota and depend on local authentication.

## Licensing

`plugins/codex` is OpenAI's official plugin, licensed under Apache-2.0. See `plugins/codex/LICENSE` and `plugins/codex/NOTICE`.

The marketplace files plus `gemini-for-claude` and `antigravity-for-claude` are MIT licensed unless a file states otherwise.
