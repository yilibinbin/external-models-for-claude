---
name: claude-review
description: Use Claude CLI from Claude Code for a read-only code review of local git changes or a branch diff.
---

# Claude Review

Use this skill when Claude Code needs an independent Claude CLI review before shipping.

Run:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" review
```

Background routing:
- Foreground use runs the normal command above.
- If parsed user argv contains `--background`, first run:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" reserve-job review
```

- Parse the returned JSON and dispatch exactly one forwarding subagent or child worker with the returned `workerCommand` JSON argv array. The child must execute that array as argv while preserving element boundaries; if forced through a shell, quote every element.
- The child runs `run-reserved-job` once through `workerCommand`; it must not inspect or reinterpret the repository.
- The parent returns the job id immediately and tells the user to use `claude-result <job-id>`.

Rules:
- Treat the output as review findings, not implementation instructions.
- Do not fix findings in the same turn unless the user explicitly asks.
- Preserve Claude's file paths, line numbers, uncertainty markers, and residual-risk notes.
- If Claude reports no findings, still report any residual risks it listed.
- Use `--structured` when the user needs schema-validated review findings; malformed structured output is a failure, not approval.
- Use `--background` for long reviews through the background routing contract above so Claude Code can continue working and retrieve results later with `claude-result`.

Arguments:
- `--base <ref>` reviews `ref...HEAD`.
- `--scope auto|working-tree|branch` is passed to the runtime for prompt context.
- `--model <model>` is passed to Claude CLI.
- `--structured` or `--review-json` returns schema-validated normalized review findings.
- `--background` starts a tracked job and returns a job id.
- `--wait` only applies to direct `--background` runtime use. It is not part of the host-forwarded `reserve-job` path, where the parent returns immediately; waiting requires polling or retrieving `claude-result <job-id>`.

Optional sizing helper:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" recommend-execution-mode
```

Use this helper when deciding whether a review should run in foreground or with `--background`.
