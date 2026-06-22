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

## Codex for Claude

本 marketplace 中的 `codex` 插件是 OpenAI 编写的 Codex Claude Code 插件文件的本地 Apache-2.0 扩展版本，文件位于 `plugins/codex`。OpenAI 署名、`LICENSE` 和 `NOTICE` 均保留；本地扩展记录在 `plugins/codex/FORK_NOTICE.md`，且不声明未经验证的上游谱系。

### 扩展命令

- `/codex:doctor` 只检查本地就绪状态，不发起模型请求。
- `/codex:github-actions render|init|validate` 会创建安全的 pull request 审阅 workflow 模板。本版本中它仍是 preview/advisory，因为 release host 上的 Codex CLI 版本和 stdin 认证契约尚未验证。
- `/codex:multi-review` 使用角色包运行聚焦的 Codex 只读审阅轮次。
- `/codex:multi-review` 在整个顺序角色运行期间只占用一个 `model-call` 容量槽。每个角色仍是一次独立的顺序 Codex turn，因此默认五角色包可在该容量槽下发起五次 Codex turn。当 model-call 限制为 `1` 时，它可能阻塞普通前台审阅命令。默认限制为 `2` 时，一个 multi-review 通常还会留下一个槽位，但两个并发 model-call 命令会耗尽容量，使第三个前台审阅返回 `capacity_blocked`。Stop gate 审阅使用独立的 `stop-gate` 容量槽。
- `--quality fast|standard|strong|max` 是 Codex 原生命令选项，会影响 task、adversarial-review 和 multi-review 的 reasoning effort。原生 `/codex:review` 只记录可见的 job-summary 标签，没有运行时效果。
- review/task 命令会拒绝未知 flag。若 prompt 或 focus 文本需要以类似 flag 的 token 开头，请先写 `--`。
- `/codex:setup` 的可选 Stop review gate 默认 fail-closed；工具、认证、超时、容量和无效输出失败都会阻止 Stop。只有当编辑器可用性优先于严格 Stop gating 时，才设置 `stopReviewGateFailOpen`。

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
