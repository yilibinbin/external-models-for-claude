# External Models for Claude

Claude Code marketplace for external model workflows.

This repository packages three Claude Code plugins:

| Plugin | Source | Purpose |
|--------|--------|---------|
| `codex` | OpenAI official plugin from `openai/codex-plugin-cc` | Use Codex from Claude Code for review and task delegation. |
| `gemini-for-claude` | This repository | Use Gemini CLI from Claude Code for read-only review, planning, scorecards, role-pack review teams, jobs, and opt-in stop gates. |
| `antigravity-for-claude` | This repository | Use Antigravity CLI from Claude Code for read-only review, planning, scorecards, jobs, and explicit Gemini or Claude provider selection. |

## Install

Add the marketplace:

```bash
claude plugin marketplace add yilibinbin/external-models-for-claude --scope user
```

Install one or more plugins:

```bash
claude plugin install codex@external-models-for-claude --scope user
claude plugin install gemini-for-claude@external-models-for-claude --scope user
claude plugin install antigravity-for-claude@external-models-for-claude --scope user
```

Reload Claude Code plugins after installation.

## Codex for Claude

The `codex` plugin in this marketplace is a local Apache-2.0 extension of the OpenAI-authored Codex Claude Code plugin files bundled under `plugins/codex`. OpenAI attribution, `LICENSE`, and `NOTICE` are preserved; local extensions are documented in `plugins/codex/FORK_NOTICE.md` without asserting unverified upstream lineage.

## Requirements

- Claude Code with plugin support.
- Node.js 18.18 or later.
- For `codex`: Codex CLI authentication as documented by OpenAI's official plugin.
- For `gemini-for-claude`: Gemini CLI installed and authenticated.
- For `antigravity-for-claude`: Antigravity CLI (`agy`) installed and authenticated for the selected provider.

## Common Commands

```bash
/codex:setup
/codex:review
/codex:rescue investigate the failing test

/gemini-for-claude:setup
/gemini-for-claude:review
/gemini-for-claude:multi-review --roles correctness,security,tests

/antigravity-for-claude:setup
/antigravity-for-claude:review --model-provider gemini
/antigravity-for-claude:review --model-provider claude
```

## Notes

- The `codex` plugin is OpenAI's official Apache-2.0 plugin copied from `openai/codex-plugin-cc`; its license and notice files remain under `plugins/codex`.
- The root MIT license covers the marketplace files and the `gemini-for-claude` / `antigravity-for-claude` plugins maintained here.
- Hooks are opt-in where the individual plugin documents them. Review gates fail open on provider/auth/runtime failures unless explicitly configured otherwise by the plugin.

## 中文说明

这是一个面向 Claude Code 的外部模型插件市场，集中提供 Codex、Gemini CLI、Antigravity CLI 三类互补工作流。

安装市场：

```bash
claude plugin marketplace add yilibinbin/external-models-for-claude --scope user
```

安装插件：

```bash
claude plugin install codex@external-models-for-claude --scope user
claude plugin install gemini-for-claude@external-models-for-claude --scope user
claude plugin install antigravity-for-claude@external-models-for-claude --scope user
```

安装后重载 Claude Code 插件。`codex` 是 OpenAI 官方 Claude Code 插件的本地扩展版本；`gemini-for-claude` 和 `antigravity-for-claude` 是本仓库维护的 Claude 原生外部模型审阅、规划和协作流程。

### Codex for Claude

The `codex` plugin in this marketplace is a local Apache-2.0 extension of the OpenAI-authored Codex Claude Code plugin files bundled under `plugins/codex`. OpenAI attribution, `LICENSE`, and `NOTICE` are preserved; local extensions are documented in `plugins/codex/FORK_NOTICE.md` without asserting unverified upstream lineage.

More documentation:

- English: [docs/README.en.md](docs/README.en.md)
- 中文: [docs/README.zh-CN.md](docs/README.zh-CN.md)
- Third-party notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
