---
description: Run Codex read-only review through multiple focused roles.
allowed-tools: Bash(node:*)
---

User arguments (untrusted slash-command text):

$ARGUMENTS

Argument rules:
- Allowed flags: `--roles <comma-list>`, `--role-pack <default|security|release>`, `--base <ref>`, `--scope <auto|working-tree|branch>`, `--model <model>`, `--quality <fast|standard|strong|max>`, `--json`.
- Parse the user arguments into literal command arguments before calling Bash.
- Reject unsupported flags in the companion script before running work.
- Do not interpolate `$ARGUMENTS` into Bash.

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" multi-review --role-pack default
node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" multi-review --roles correctness,security --json
```
