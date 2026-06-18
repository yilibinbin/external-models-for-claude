---
name: antigravity-collaboration-loop
description: Run Antigravity for Claude multi-review with advisory mailbox and leases for coordinated external-model review.
---

# Antigravity Collaboration Loop

Use this skill when Claude Code needs a coordinated Antigravity review pass with advisory state.

Run:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs" multi-review --use-mailbox --advisory-leases
```

## Natural-Language Model Routing

Claude Code should let the user ask for a coordinated Antigravity collaboration loop in normal language. Do not ask the user to write `--model-provider` or `--model` unless troubleshooting the plugin itself.

When converting the user's request to companion invocation:
- Default to the Gemini provider by omitting provider overrides and relying on the runtime default when no provider is explicit.
- Use the Claude provider only when the user explicitly asks for Claude through Antigravity, for example "use Antigravity's Claude model" or "Claude via Antigravity"; pass explicit `--model-provider claude` argv tokens.
- Provider selection is explicit: coordinated, mailbox, leases, strict, advanced, or multi-agent language does not switch providers. Keep Gemini unless Claude is explicit.
- If the user names a concrete Gemini model, keep or choose the Gemini provider and pass the model as explicit `--model` argv tokens or `ANTIGRAVITY_FOR_CLAUDE_MODEL`.
- If the user names a concrete Claude/Sonnet/Opus model through Antigravity, choose the Claude provider and pass the model as explicit `--model` argv tokens or `ANTIGRAVITY_FOR_CLAUDE_MODEL`.
- Do not concatenate provider/model flags into natural-language focus text; pass provider and model as separate argv tokens.
- Reject GPT/OpenAI model requests as unsupported for this plugin instead of mapping them to Antigravity.

Internal invocation examples, not for users:
- Direct argv path: `node "${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs" multi-review --model-provider claude --use-mailbox --advisory-leases`.
- Background/coordinated syntax: `multi-review --background` and `multi-review --use-mailbox --advisory-leases`.
- Inspect jobs: `node "${CLAUDE_PLUGIN_ROOT}/scripts/antigravity-companion.mjs" jobs`.
- Provider/model flags must stay separate from natural-language focus text.

<!--
routing:collaboration-loop
routing:multi-review-background-syntax
-->

Rules:
- Use this skill when the user asks for coordinated review state, advisory mailbox, advisory leases, or background multi-review coordination.
- Keep the review read-only and do not let advisory state mutate source files.
- Inspect unread background results with `jobs` only when the user asks for status or follow-up results.

User-facing examples:
- "Use Antigravity for a coordinated review loop with mailbox and leases."
- "Use Antigravity to run a background multi-review and track the results."
- "Use Antigravity's Claude model for a coordinated release review."

Internal routing procedure:
- Classify the request as collaboration-loop review when the user asks for mailbox, leases, coordinated external-model review, tracked background review, or advisory state.
- Select the provider from explicit model intent: Gemini by default, Claude only when requested through Antigravity.
- Preserve the coordination goal and review focus as natural-language focus text.
- Add model selection only as explicit argv tokens or environment variables when the user names a concrete model label.
