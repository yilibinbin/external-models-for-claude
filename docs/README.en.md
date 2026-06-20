# External Models for Claude

`external-models-for-claude` is a Claude Code marketplace for multi-model development workflows.

## Included Plugins

- `codex`: OpenAI's official Claude Code plugin for Codex review and delegation.
- `gemini-for-claude`: Gemini CLI review, planning, scorecards, role packs, tracked jobs, GitHub Actions workflow rendering, and opt-in stop gates.
- `antigravity-for-claude`: Antigravity CLI review, planning, scorecards, tracked jobs, GitHub Actions workflow rendering, and explicit Gemini/Claude provider selection.
- `claude-for-claude`: Isolated Claude CLI child-process review, planning, scorecards, role packs, tracked jobs, GitHub Actions workflow rendering, and opt-in stop gates.

## Installation

```bash
claude plugin marketplace add yilibinbin/external-models-for-claude --scope user
claude plugin install codex@external-models-for-claude --scope user
claude plugin install gemini-for-claude@external-models-for-claude --scope user
claude plugin install antigravity-for-claude@external-models-for-claude --scope user
claude plugin install claude-for-claude@external-models-for-claude --scope user
```

Reload Claude Code plugins after installing.

## Provider Setup

Run the setup command for the plugin you install:

```bash
/codex:setup
/gemini-for-claude:setup
/antigravity-for-claude:setup
/claude-for-claude:doctor
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
claude plugin validate --strict plugins/claude-for-claude
python3 -m pytest -q
```

Live provider smoke tests are opt-in because they consume provider quota and depend on local authentication.

## Licensing

`plugins/codex` is OpenAI's official plugin, licensed under Apache-2.0. See `plugins/codex/LICENSE` and `plugins/codex/NOTICE`.

The marketplace files plus `gemini-for-claude`, `antigravity-for-claude`, and `claude-for-claude` are MIT licensed unless a file states otherwise.
