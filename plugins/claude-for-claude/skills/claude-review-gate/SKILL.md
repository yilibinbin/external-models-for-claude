---
name: claude-review-gate
description: Configure the opt-in Claude Stop review gate for Claude for Claude.
---

# Claude Review Gate

Use this skill when the user wants Claude to run a Stop-time gate before Claude Code finishes a turn.

Enable the gate:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" setup --enable-review-gate --review-gate-mode multi-role
```

Disable the gate:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" setup --disable-review-gate
```

Inspect gate status:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" setup
```

Manual gate run:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/claude-companion.mjs" review-gate
```

Rules:
- The hook is opt-in. Installing the plugin does not enable blocking behavior.
- The gate reviews current git working-tree changes, not an exact per-turn edit set.
- The enabled gate uses the default multi-role review set: correctness, security, tests, release, adversarial.
- Only explicit `BLOCK:` verdicts from Claude block Stop.
- Claude CLI failures, timeouts, invalid gate output, or missing Claude warn but do not block Stop.
- Export `CLAUDE_FOR_CLAUDE_REVIEW_GATE=off` in the environment that launches Claude Code hooks to bypass the gate immediately.
- Unchanged diffs that already received an all-`ALLOW:` gate result are skipped until the working-tree diff changes.
- Do not add a `hooks` field to `.claude-plugin/plugin.json`; the standard `hooks/hooks.json` file is auto-discovered by the plugin runtime.

After install or upgrade, check Claude Code Settings > Hooks and trust or enable the `Claude for claude` Stop hook if prompted.
