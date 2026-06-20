---
name: claude-rescue
description: Ask Claude CLI for read-only rescue diagnosis when Claude Code is stuck, failing tests, or uncertain about recovery.
---

# Claude Rescue

Use this skill when Claude Code needs an independent Claude diagnosis for a stuck implementation, failing validation, confusing git state, or unclear next recovery step.

Run:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" rescue
```

Background routing:
- Foreground use runs the normal command above.
- If parsed user argv contains `--background`, first run:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" reserve-job rescue
```

- Parse the returned JSON and dispatch exactly one forwarding subagent or child worker with the returned `workerCommand` JSON argv array. The child must execute that array as argv while preserving element boundaries; if forced through a shell, quote every element.
- The child runs `run-reserved-job` once through `workerCommand`; it must not inspect or reinterpret the repository.
- The parent returns the job id immediately and tells the user to use `claude-result <job-id>`.

Rules:
- Default mode is read-only.
- Claude must diagnose and propose recovery steps, not edit files.
- Claude Code remains responsible for applying any fixes after reviewing the diagnosis.
- Claude native session flags are opt-in and capability-gated by the runtime; unsupported flags fail before Claude invocation.

Arguments:
- `--base <ref>` includes branch diff context when available.
- `--scope auto|working-tree|branch` controls git context selection.
- `--path <path>` or `--paths <path>` filters git context.
- `--model <model>` is passed to Claude CLI.
- `--resume [latest|id]` asks Claude CLI to resume when supported.
- `--fresh` avoids resume routing.
- `--session-id <uuid>` asks Claude CLI to use an explicit session id when supported.
- `--worktree [name]` asks Claude CLI to use its native worktree mode when supported.
- `--background` starts a tracked job and returns a job id.
- `--wait` only applies to direct `--background` runtime use. It is not part of the host-forwarded `reserve-job` path, where the parent returns immediately; waiting requires polling or retrieving `claude-result <job-id>`.
