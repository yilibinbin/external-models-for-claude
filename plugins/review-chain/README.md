# review-chain

A shared **serial adversarial-review chain** for the `external-models-for-claude`
marketplace. Instead of invoking one external model at a time, this plugin runs the whole
panel of installed external-model reviewers in one serial pass and has the main-thread Claude
broker their findings to a single verdict.

## What it does

It implements the serial adversarial-review protocol:

1. **Claude (main thread)** reviews the diff and produces an initial findings list.
2. **Gemini Pro — via the Antigravity plugin** (`antigravity-for-claude@external-models-for-claude`) — receives the diff plus Claude's findings; may confirm, refute, or add.
3. **Codex** (`codex@external-models-for-claude`) — receives the diff plus Claude's and Gemini's findings; may confirm, refute, or add.
4. **Main thread synthesizes** — normalize/dedup findings, collect explicit confirm/refute/abstain positions, relay contested findings verbatim across a bounded rebuttal loop, arbitrate deadlocks, and apply an evidence gate.

The serial order is deliberate: each reviewer is fed every prior reviewer's findings, so a
later model can overturn an earlier model's mistake. **The order must not decide the
outcome** — findings survive on evidence and explicit consensus, never on which stage raised
them.

## Auto-joining future plugins

The chain enumerates review-capable plugins at runtime from `claude plugin list --json` and
probes each for an `adversarial-review` capability by convention (an `adversarial-review`
command/skill plus a companion that advertises the `adversarial-review` subcommand). Any
future external-model plugin that ships that capability joins the panel automatically — no
edit to this plugin required.

## Usage

Model-invocable skill (natural language triggers it):

> "Run a serial adversarial review of this diff."
> "Run the multi-model review chain."

Or the explicit command:

```
/review-chain:serial-review [--scope auto|working-tree|branch] [--base <ref>] [focus ...]
```

## Install

```bash
claude plugin marketplace add yilibinbin/external-models-for-claude --scope user
claude plugin install review-chain@external-models-for-claude --scope user
```

To move to a newer version, the runtime loads from a version-pinned cache, so a bare reinstall
is a no-op. Re-pin with:

```bash
claude plugin uninstall review-chain@external-models-for-claude
claude plugin marketplace update external-models-for-claude
claude plugin install review-chain@external-models-for-claude --scope user
```

## Notes

- Reviews are read-only; the chain never edits, commits, or pushes.
- Reviewers run **strictly serially**, one at a time, to respect the panel's process-level
  contention limits.
- The chain is the one plugin in this marketplace that references its sibling plugins by
  handle, because orchestrating them is its whole job.
