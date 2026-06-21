---
description: Run Codex read-only review through multiple focused roles.
allowed-tools: Bash(node:*)
---

User arguments (untrusted slash-command text):

$ARGUMENTS

Argument rules:
- Allowed flags: `--roles <comma-list>`, `--role-pack <default|security|release>`, `--base <ref>`, `--scope <auto|working-tree|branch>`, `--model <model>`, `--quality <fast|standard|strong|max>`, `--json`.
- Select exactly one companion invocation.
- Parse the user arguments into literal command arguments before calling Bash, and append only supported flags as separate arguments.
- Reject unsupported flags in the companion script before running work.
- Do not interpolate `$ARGUMENTS` into Bash.
- Return the command stdout verbatim, exactly as-is.

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" multi-review --role-pack default
```
