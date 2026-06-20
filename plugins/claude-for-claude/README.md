# Claude for Claude

Claude for Claude lets Claude Code ask a separate `claude -p` child process for read-only review, planning, scorecards, role-pack review teams, tracked jobs, and an opt-in Stop hook review gate.

中文说明：这个插件让 Claude Code 可以调用一个隔离的 Claude CLI 子进程做只读复审、计划审阅、多角色审阅、后台任务和可选 Stop 阶段门禁。默认不写文件，不通过其他 provider 转发。

## Install

```bash
claude plugin marketplace add https://github.com/yilibinbin/external-models-for-claude --scope user
claude plugin install claude-for-claude@external-models-for-claude --scope user
```

## Commands

- `/claude-for-claude:doctor` checks local CLI availability and plugin state.
- `/claude-for-claude:review` reviews current git changes.
- `/claude-for-claude:adversarial-review` applies stricter bug/security/test lenses.
- `/claude-for-claude:multi-review` runs role-pack review teams.
- `/claude-for-claude:plan-review --plan <file>` reviews a saved plan.
- `/claude-for-claude:plan` asks for an implementation plan.
- `/claude-for-claude:assisted-review` runs bounded advisory review rounds.
- `/claude-for-claude:status`, `/result`, and `/cancel` manage tracked jobs.
- `/claude-for-claude:review-gate --enable` enables the opt-in Stop hook gate for the current workspace.

## Runtime

Child Claude calls use:

```bash
claude -p --safe-mode --no-session-persistence --tools "" --output-format json
```

The plugin sets `CLAUDE_FOR_CLAUDE_CHILD=1` so hooks can skip recursive child invocations. The default model is the user's configured Claude default. Use `--model <alias>` or `CLAUDE_FOR_CLAUDE_MODEL` when a specific Claude alias is needed.

## Safety Notes

- Review commands are read-only by default.
- Raw slash-command text is not interpolated into shell commands.
- Stop gate failures are fail-open by default: missing CLI, auth errors, timeout, invalid output, and hook errors warn instead of blocking.
- State is stored under `CLAUDE_PLUGIN_DATA` when available, otherwise under the user's Claude data directory.

## 中文

安装后可直接用自然语言让 Claude 调用 Claude for Claude 做独立复审。需要强制指定模型时，可以在命令中加 `--model sonnet`、`--model opus` 或其他本机 Claude Code 支持的别名。Stop gate 默认只安装不启用，需要手动运行 `review-gate --enable`。
