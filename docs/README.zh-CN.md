# External Models for Claude

`external-models-for-claude` 是一个面向 Claude Code 的多模型工作流插件市场。

## 收录插件

- `codex`：OpenAI 官方 Codex for Claude Code 插件，用于 Codex 审阅和任务委托。
- `gemini-for-claude`：通过 Gemini CLI 提供只读审阅、计划审阅、scorecard、角色包、多任务、GitHub Actions 模板和可选 Stop gate。
- `antigravity-for-claude`：通过 Antigravity CLI 提供只读审阅、计划审阅、scorecard、多任务、GitHub Actions 模板，并支持显式选择 Gemini 或 Claude provider。

## 安装

```bash
claude plugin marketplace add yilibinbin/external-models-for-claude --scope user
claude plugin install codex@external-models-for-claude --scope user
claude plugin install gemini-for-claude@external-models-for-claude --scope user
claude plugin install antigravity-for-claude@external-models-for-claude --scope user
```

安装后请重载 Claude Code 插件。

## 初始化

按需运行对应插件的 setup：

```bash
/codex:setup
/gemini-for-claude:setup
/antigravity-for-claude:setup
```

Antigravity 可以显式选择 provider：

```bash
/antigravity-for-claude:review --model-provider gemini
/antigravity-for-claude:review --model-provider claude
```

默认 provider 也可以通过插件 setup/status 流程或插件文档中的环境变量配置。

## 发布验证

正式发布前应通过：

```bash
claude plugin validate --strict .claude-plugin/marketplace.json
claude plugin validate --strict plugins/codex
claude plugin validate --strict plugins/gemini-for-claude
claude plugin validate --strict plugins/antigravity-for-claude
python3 -m pytest -q
```

真实 provider smoke 测试会消耗额度，并依赖本机认证，因此默认是显式启用。

## 许可

`plugins/codex` 是 OpenAI 官方插件，使用 Apache-2.0 许可。请见 `plugins/codex/LICENSE` 和 `plugins/codex/NOTICE`。

本仓库 marketplace 文件以及 `gemini-for-claude`、`antigravity-for-claude` 默认使用 MIT 许可，除非具体文件另有说明。
