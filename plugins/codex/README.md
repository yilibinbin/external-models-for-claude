# Codex for Claude

Use OpenAI Codex from Claude Code for code review, adversarial review, rescue, and delegated implementation tasks.

Install from this marketplace:

```bash
claude plugin marketplace add yilibinbin/external-models-for-claude --scope user
claude plugin install codex@external-models-for-claude --scope user
```

The `codex` plugin in this marketplace is a local Apache-2.0 extension of the OpenAI-authored Codex Claude Code plugin files bundled under `plugins/codex`. OpenAI attribution, `LICENSE`, and `NOTICE` are preserved; local extensions are documented in `plugins/codex/FORK_NOTICE.md` without asserting unverified upstream lineage.

This plugin keeps Codex as the only provider. It does not route requests to Gemini, Antigravity, or Claude providers.
