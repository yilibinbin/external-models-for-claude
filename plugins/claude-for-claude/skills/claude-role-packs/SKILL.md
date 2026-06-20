---
name: claude-role-packs
description: Inspect Claude for Claude reviewer role packs and run built-in Claude review teams.
---

# Claude Role Packs

Use this skill when Claude Code needs a named Claude reviewer team instead of manually listing roles.

List packs:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" roles list
```

Inspect a built-in pack:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" roles inspect
```

Run a built-in pack:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" multi-review --role-pack
```

Rules:
- Role packs are Claude for Claude reviewer presets, not Claude extensions.
- Built-in packs can run through normal parallel Claude CLI fan-out or `multi-review --agent-team native-agents --role-pack <pack>`.
- Use `--agent-team native-agents --native-structured` when the user explicitly wants a validated aggregate JSON result from a built-in pack.
- User-authored role packs are validate/inspect-only in this release; do not execute `--role-pack-file`.
- Treat role-pack output as review findings, not implementation instructions.
- Preserve the selected pack name, role list, and residual risks when reporting results.
- `review-gate --role-pack <pack>` is manual-only and rejects gate-incompatible packs before Claude is called.

Common packs:
- `minimal`: correctness only.
- `release`: release, tests, correctness, and security.
- `security`: security, correctness, and adversarial.
- `default`: the existing default multi-review role set.
