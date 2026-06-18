# Antigravity for Claude

Version: 0.1.0

Claude Code plugin that invokes the local Antigravity CLI (`agy`) for independent read-only review, planning, adversarial critique, rescue diagnosis, multi-role review, structured reports, background jobs, advisory coordination, GitHub Actions workflow rendering, release checks, and an opt-in Stop hook gate.

Antigravity for Claude has operational maturity for plugin-managed workflows: bounded CLI invocation, explicit model selection, repo-external state, sanitized reports, lifecycle hooks, release checks, and `real-smoke` is opt-in. It does not claim Claude SDK, Gemini native-agent, or ultrareview parity. Claude-through-Antigravity is an explicit Antigravity model-provider choice and is available only through explicit Antigravity provider selection.

## Agy-Native Maturity Boundary

This plugin absorbs mature workflow patterns from Claude for Claude Code only when they make sense for Antigravity:

- `agy` remains the only model execution command.
- Gemini remains the default provider.
- Claude-through-Antigravity is explicit and stays separate from Claude for Claude Code.
- Fable, Claude SDK subagents, Claude ultrareview, Claude Code `--fallback-model`, and Claude Code permission brokering are not Antigravity features.
- `doctor` is cheap by default and does not call a model.
- `real-smoke` is still opt-in because it requires an authenticated `agy` account and live provider quota.

## Requirements

- Claude Code with plugin support
- Antigravity CLI available as `agy`, `AGY_CLI_PATH`, or `ANTIGRAVITY_CLI_PATH`
- Node.js 20 or newer
- Git repository for review context collection

## Global Resource Governor

Antigravity for Claude uses a file-backed global governor to keep several Claude Code conversations, Stop hooks, background jobs, and multi-role reviews from starting unlimited `agy` work at once. The default lease directory is `~/.claude/antigravity-for-claude/global-resource-locks`; set `ANTIGRAVITY_FOR_CLAUDE_RESOURCE_LOCK_DIR` to move it.

Covered paths:

- Foreground `review`, `adversarial-review`, `plan`, and `rescue`
- Plugin-managed `multi-review`
- Stop hook `review-gate`
- `--background`, `reserve-job`, and `run-reserved-job`

Defaults are conservative: at most two concurrent Antigravity model calls and two background jobs per user account. Tune them with:

```bash
ANTIGRAVITY_FOR_CLAUDE_GLOBAL_MAX_MODEL_CALLS=2
ANTIGRAVITY_FOR_CLAUDE_GLOBAL_MAX_BACKGROUND_JOBS=2
ANTIGRAVITY_FOR_CLAUDE_MULTI_REVIEW_MAX_PARALLEL=2
```

When capacity is full, foreground commands return `capacity_blocked` with exit status 75 before starting `agy`. Stop hooks fail open with stderr diagnostics. `multi-review` automatically uses bounded fan-out and becomes sequential when the configured/global model-call limit is 1. Set `ANTIGRAVITY_FOR_CLAUDE_RESOURCE_GOVERNOR=off` only for local debugging.

The plugin also retries short-lived local spawn pressure such as `EAGAIN`, `EMFILE`, `ENFILE`, and `ENOBUFS` with a bounded backoff. This does not raise concurrency limits; it only makes already-governed work more tolerant when the OS briefly cannot start a helper process.

## Model Selection

Users can ask for Antigravity in natural language. Claude Code should map the request to internal Antigravity arguments; users do not need to write `--model-provider` or `--model`.

Default behavior:

- Use the Gemini provider.
- Use `Gemini 3.1 Pro (High)` unless `ANTIGRAVITY_FOR_CLAUDE_MODEL` or `ANTIGRAVITY_FOR_CLAUDE_GEMINI_MODEL` overrides it.
- Treat "strict", "deep", "advanced", "high-confidence", and "multi-agent" as review strength, not a request to switch providers.

Explicit Claude-through-Antigravity behavior:

- Use the Claude provider only when the user clearly asks for Claude through Antigravity.
- Use `Claude Sonnet 4.6 (Thinking)` unless `ANTIGRAVITY_FOR_CLAUDE_MODEL` or `ANTIGRAVITY_FOR_CLAUDE_CLAUDE_MODEL` overrides it.
- Keep Claude-through-Antigravity separate from `Claude provider plugin`; this plugin still calls `agy`, not Claude Code.

Examples users can say:

- "Use Antigravity to review the current changes."
- "Use Antigravity for a strict multi-role release review."
- "Use Antigravity's Claude model to challenge this plan."

Advanced environment defaults:

```bash
ANTIGRAVITY_FOR_CLAUDE_MODEL_PROVIDER=gemini
ANTIGRAVITY_FOR_CLAUDE_GEMINI_MODEL="Gemini 3.1 Pro (High)"
ANTIGRAVITY_FOR_CLAUDE_CLAUDE_MODEL="Claude Sonnet 4.6 (Thinking)"
```

Workflow generation note:

- `github-actions init` persists the selected provider into the generated workflow. Use `ANTIGRAVITY_FOR_CLAUDE_MODEL_PROVIDER` for workflow generation only when you intend that provider to be committed for the team. Provider-specific model defaults remain runtime-owned unless `ANTIGRAVITY_FOR_CLAUDE_MODEL` is explicitly set.

The plugin rejects GPT/OpenAI model labels and never passes `--dangerously-skip-permissions`.

## Commands

- `setup`
- `capabilities`
- `review`
- `adversarial-review`
- `multi-review`
- `plan`
- `plan-review`
- `assisted-review`
- `rescue`
- `review-gate`
- `real-smoke`
- `release-check`
- `report`
- `roles`
- `jobs`
- `status`
- `result`
- `cancel`
- `reserve-job`
- `run-reserved-job`
- `mailbox`
- `leases`
- `github-actions`

## Quality Loop

Antigravity for Claude includes a provider-native quality loop for release work:

```bash
antigravity-review --scorecard --json
antigravity-plan --taskset "Plan the remaining release work."
antigravity-plan-review --plan task_plan.md --scorecard --roles correctness,security,tests,release
antigravity-assisted-review --taskset ts-example --max-review-rounds 2
```

The scorecard contract is normalized locally before Claude Code consumes it. Tasksets are stored outside the repository under the plugin state directory and contain advisory subtasks only. Plan review reads only regular files inside the current workspace and rejects symlinks or paths outside the repo. Assisted review never edits files, commits, pushes, opens PRs, or closes issues; it stops when the score threshold is met, a repeated blocker/no-improvement condition appears, a provider failure is classified, or the round cap is reached.

Natural-language routing follows the same model-selection boundary as the rest of this plugin: Gemini is the default provider, and Claude-through-Antigravity is used only when the user explicitly asks for Claude through Antigravity.

## Smoke And CI

`real-smoke` is opt-in:

```bash
ANTIGRAVITY_FOR_CLAUDE_REAL_SMOKE=1 node "${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs" real-smoke --quick
```

GitHub Actions rendering and validation are available through `github-actions render|init|validate`. CI runs require an authenticated `agy` command in the runner environment; release checks validate the generated workflow offline but do not authenticate Antigravity.
