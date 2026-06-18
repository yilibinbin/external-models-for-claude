---
name: antigravity-github-actions-review
description: Use Antigravity CLI from Claude Code to review GitHub Actions workflow changes and PR-review automation risk.
---

# Antigravity GitHub Actions Review

Use this skill when the user asks Antigravity to inspect GitHub Actions workflow changes, review automation, or fork-safety concerns.

Run:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs" review "GitHub Actions workflow safety, fork PR behavior, secret exposure, permissions, and immutable plugin refs."
```

Install the fork-safe PR review workflow:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs" github-actions init
```

Validate an existing workflow:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs" github-actions validate
```

## Natural-Language Model Routing

Claude Code should let the user ask for Antigravity GitHub Actions review in normal language. Do not ask the user to write `--model-provider` or `--model` unless troubleshooting the plugin itself.

When converting the user's request to companion invocation:
- Default to the Gemini provider by omitting provider overrides and relying on the runtime default when no provider is explicit.
- Use the Claude provider only when the user explicitly asks for Claude through Antigravity, for example "use Antigravity's Claude model" or "Claude via Antigravity"; pass explicit `--model-provider claude` argv tokens.
- Provider selection is explicit: strict, deep, high-confidence, advanced, or multi-agent language does not switch providers. Keep Gemini unless Claude is explicit.
- If the user names a concrete Gemini model, keep or choose the Gemini provider and pass the model as explicit `--model` argv tokens or `ANTIGRAVITY_FOR_CLAUDE_MODEL`.
- If the user names a concrete Claude/Sonnet/Opus model through Antigravity, choose the Claude provider and pass the model as explicit `--model` argv tokens or `ANTIGRAVITY_FOR_CLAUDE_MODEL`.
- Do not concatenate provider/model flags into natural-language focus text; pass provider and model as separate argv tokens.
- Reject GPT/OpenAI model requests as unsupported for this plugin instead of mapping them to Antigravity.

Internal invocation examples, not for users:
- Direct argv path: `node "${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs" review --model-provider claude`.
- GitHub Actions review focus path: `node "${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs" review --model-provider claude "GitHub Actions workflow safety, fork PR behavior, secret exposure, permissions, and immutable plugin refs."`.
- Workflow init path: `node "${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs" github-actions init` uses the runtime Gemini default unless provider/model are explicitly set as separate argv tokens.
- Provider/model flags must stay separate from natural-language focus text.

<!--
routing:github-actions-review
routing:github-actions-prefix-dedup
-->

Rules:
- This skill is read-only unless the user explicitly asks to render or initialize the workflow file.
- Do not use `pull_request_target` unless the user explicitly asks to analyze that risk.
- Check workflow permissions, secret access, fork PR behavior, pinned refs, and install commands.
- CI must provide an authenticated `agy` command; the generated workflow does not embed credentials.
- Treat findings as review input for Claude Code to reconcile.

User-facing examples:
- "Use Antigravity to review the GitHub Actions workflow for fork safety."
- "Use Antigravity for a strict review of the PR review workflow."
- "Use Antigravity's Claude model to review this workflow permission change."

Internal routing procedure:
- Classify the request as GitHub Actions review when the user asks about workflow safety, fork PR behavior, PR-review automation, permissions, secrets, pinned refs, or generated Antigravity review workflows.
- Select the provider from explicit model intent: Gemini by default, Claude only when requested through Antigravity.
- Use `github-actions init` only when the user asks to install or render the fork-safe workflow; otherwise use read-only `review` focus.
- Preserve the workflow focus as natural-language focus text. Prepend the GitHub Actions safety prefix only when the user's focus is broad or absent; if the user already supplied a specific workflow-safety focus, do not duplicate it.
- Add model selection only as explicit argv tokens or environment variables when the user names a concrete model label.
