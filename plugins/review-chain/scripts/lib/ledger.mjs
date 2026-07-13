// Findings ledger: the shared record the serial chain accumulates across stages.
// Findings — not verdicts — are the unit of record, because the protocol is
// finding-centric (every finding needs explicit confirm/refute/abstain).
//
// Each stage stores its reviewer's RAW output verbatim (byte-for-byte). The rebuttal
// loop requires in-full relay, so this layer never summarizes or rewrites — it only
// normalizes the coarse gate signal alongside the raw text.

import fs from "node:fs";
import path from "node:path";

// Collapse the two divergent verdict vocabularies onto one coarse 3-value gate. This is
// a SIGNAL only, never the outcome — the protocol forbids stage/order deciding a finding.
//   codex:        approve -> clean, needs-attention -> attention
//   gemini/agy:   PASS -> clean, CONTESTED -> attention, REJECT -> blocking
//   anything else -> attention (an unrecognized verdict must never silently pass as clean)
export function normalizeGate(rawVerdict) {
  const v = String(rawVerdict ?? "").trim().toLowerCase();
  if (v === "approve" || v === "pass") {
    return "clean";
  }
  if (v === "reject") {
    return "blocking";
  }
  if (v === "needs-attention" || v === "needs_attention" || v === "contested") {
    return "attention";
  }
  return "attention";
}

export function initLedger(ledgerPath, meta = {}) {
  const ledger = {
    target: meta.target ?? null,
    createdMode: meta.mode ?? null,
    stages: []
  };
  writeLedger(ledgerPath, ledger);
  return ledger;
}

export function appendStage(ledgerPath, stage) {
  const ledger = readLedger(ledgerPath);
  ledger.stages.push({
    reviewer: stage.reviewer ?? null,
    rawVerdict: stage.rawVerdict ?? null,
    normalizedGate: normalizeGate(stage.rawVerdict),
    findings: Array.isArray(stage.findings) ? stage.findings : [],
    rawOutput: typeof stage.rawOutput === "string" ? stage.rawOutput : ""
  });
  writeLedger(ledgerPath, ledger);
  return ledger;
}

export function readLedger(ledgerPath) {
  const text = fs.readFileSync(ledgerPath, "utf8");
  return JSON.parse(text);
}

function writeLedger(ledgerPath, ledger) {
  fs.mkdirSync(path.dirname(ledgerPath), { recursive: true });
  fs.writeFileSync(ledgerPath, `${JSON.stringify(ledger, null, 2)}\n`, "utf8");
}
