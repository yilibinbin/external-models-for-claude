---
name: serial-adversarial-review
description: Run all installed external-model plugins as one serial adversarial review chain — Claude, then Gemini via Antigravity, then Codex — accumulating findings, relaying rebuttals verbatim, and applying an evidence gate. Use for "serial adversarial review", "multi-model review", or reviewing a diff with the full external-model panel.
---

# Serial Adversarial Review

Use this skill when a change warrants review by the whole external-model panel, not one
model. You (main-thread Claude) are the **sole broker**: the reviewer models cannot talk to
each other, so every exchange passes through you. The mechanical companion enumerates
plugins, builds the diff, dispatches each reviewer, and keeps the findings ledger; **you** do
the judgment — normalize, collect positions, relay rebuttals, arbitrate, and decide.

> **The serial order MUST NOT decide the outcome.** A correct finding raised early must not
> die because a later model dismissed it, and a finding raised last gets no free pass.
> Whether a finding survives depends on **evidence and explicit consensus**, never on which
> stage produced it.

## Reviewers run strictly serially

Dispatch **one reviewer at a time** and wait for it to finish before the next. Never fan out
— overlapping external reviews contend badly and explode latency. Reviews are app-server /
CLI backed and take **several minutes**; dispatch them **detached** and wait on the PID, never
inline.

The companion handles the per-reviewer flag dialect and the codex session-env unset for you.
Enumerate first, then dispatch in order:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/review-chain-companion.mjs" enumerate --json
```

The codified panel order is:
1. **Claude (you, main thread)** — review the diff first, produce the initial findings list.
2. **Gemini Pro — via the Antigravity plugin** (`antigravity-for-claude@external-models-for-claude`) — fed the diff + your findings.
3. **Codex** (`codex@external-models-for-claude`) — fed the diff + your findings + Gemini's.
4. **You synthesize** — consolidate the surviving findings into the final verdict.

Enumerate reports every review-capable plugin (so a future plugin auto-joins the panel). The
Gemini stage runs through Antigravity per the governing rule.

## Procedure

### Stage 0 — build the diff and your own findings
Build the shared target and initialize the ledger. **Keep the ledger and all reviewer
output files OUTSIDE the target repo working tree** — a reviewer with no `--scope`
(Antigravity) reviews the full working tree, so an artifact left in the repo would be
reviewed as part of the diff. Use a temp path such as `"${TMPDIR:-/tmp}/review-chain/ledger.json"`;
the `dispatch` command already defaults its own output there.

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/review-chain-companion.mjs" build-diff --scope auto --json
node "${CLAUDE_PLUGIN_ROOT}/scripts/review-chain-companion.mjs" ledger init --out <ledger-outside-repo> --target "<target label>"
```

Review the diff yourself and record your initial findings.

### Stage 1 — Gemini via Antigravity, then Stage 2 — Codex
Dispatch each reviewer serially. The companion maps flags and, **for the codex reviewer only**,
unsets `CODEX_COMPANION_SESSION_ID` and `CLAUDE_CODE_SESSION_ID` (its liveness gate aborts a
job that inherits the host session) and spawns detached:

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/review-chain-companion.mjs" dispatch --plugin antigravity-for-claude --scope <scope> --pid-file <pid-outside-repo> --out-file <out-outside-repo>
# Block until the detached reviewer exits. Use the companion's `wait` (a node: command)
# — the command wrapper only permits Bash(node:*)/Bash(git:*), so shell `wait`/`sleep`
# are NOT available to you.
node "${CLAUDE_PLUGIN_ROOT}/scripts/review-chain-companion.mjs" wait --pid-file <pid-outside-repo>
# then record the reviewer's verdict + verbatim output:
node "${CLAUDE_PLUGIN_ROOT}/scripts/review-chain-companion.mjs" ledger append --out <ledger-outside-repo> --reviewer antigravity --verdict <PASS|CONTESTED|REJECT> --raw-file <out-outside-repo>
```

Repeat for `--plugin codex`. Feed each reviewer the diff **plus the full current ledger** so a
later reviewer can challenge an earlier one.

> **Antigravity diff caveat.** Antigravity has no `--scope`/`--base`; it always reviews the
> full working+staged tree. So it may see a wider diff than the `--base` target the others see.
> When weighing an Antigravity finding, check it against the correct target diff — do not accept
> or reject it on a diff mismatch it never saw.

### Stage 3 — normalize and dedup
Before anything else, merge semantically equivalent findings raised at different stages into
**one** finding, unioning their evidence. Dedup by **meaning, not wording** — otherwise the same
issue gets different scrutiny depending on who phrased it, re-injecting an order effect.

### Stage 4 — collect explicit positions
For **each** normalized finding, regardless of which stage raised it, collect an explicit
**confirm / refute / abstain** (each with its evidence) from every reviewer that has not already
stated one. **Silence is never consent.** A finding is *settled* once every reviewer has taken an
evidence-backed position or abstained. A position discarded for lack of evidence counts as an
abstention, not an open slot.

### Stage 5 — evidence gate
Default **every** finding to spurious unless grounded in concrete evidence from the diff or a
reproduction. This applies to the initial finding, every confirmation, every refutation, and the
deadlock ruling alike. Anything that survives on no concrete evidence does not land.

### Stage 6 — contested rebuttal loop (broker discipline)
A finding may have more than two opposing positions; treat each distinct evidence-backed position
as its own side.

1. **Gate before looping.** A refutation or confirmation with no concrete evidence is discarded
   up front and does **not** make a finding contested — filter it before opening the loop.
2. **Open the loop only on evidence-backed disagreement.** Relay each side's position to the
   other holders **verbatim and in full**. As broker you transmit every side's strongest points
   without picking a winner or filtering; do not paraphrase in a way that favors any side. If an
   argument is too long to relay whole, you may omit whole trailing chunks labeled
   `[truncated for length]` — never rewrite, summarize, or selectively excerpt.
3. **Rebut to consensus.** Keep relaying across rounds until they converge: all but one position
   is conceded on the evidence, or all non-abstaining holders reach the same verdict. Never
   average positions — record the converged conclusion, not a blend.

**HARD CAP: 3 rounds** per contested finding.

### Stage 7 — deadlock arbitration
If a finding has not converged at the 3-round cap, **you arbitrate on evidence**: weigh every
side's evidence directly, rule real or spurious, and record the ruling with its reason. You are
both a reviewer and the final arbiter — an accepted structural limit, there is no fourth party to
recuse to — so when arbitrating a finding you yourself raised or refuted, **flag that
conflict of interest** in the record and hold the ruling to a stricter evidence bar. Never leave a
finding unresolved and never punt a deadlock past the cap.

### Stage 8 — synthesize
Consolidate the surviving findings into the final verdict. Surface conflicts rather than blending
them. Report each landed finding with its evidence and the converged/arbitrated conclusion.

## Broker discipline checklist
- Relay every rebuttal **verbatim and in full** (only `[truncated for length]` as an escape).
- Never let the serial order decide a finding.
- Never treat a reviewer's silence as agreement.
- Default every claim spurious until its own evidence stands.
- One reviewer at a time; wait on each PID before the next.
