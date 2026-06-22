export function classifyStopGateResult(result, options = {}) {
  const failOpen = Boolean(options.failOpen);
  const reason = String(result?.reason || "").trim() || "Codex stop review gate did not return a reason.";
  const verdict = String(result?.verdict || "").trim().toUpperCase();

  if (result?.ok && verdict === "BLOCK") {
    return {
      decision: "block",
      verdict: "BLOCK",
      reason,
      toolFailure: false
    };
  }

  if (result?.ok && (verdict === "ALLOW" || !verdict)) {
    return {
      decision: "allow",
      verdict: verdict || null,
      reason,
      toolFailure: false
    };
  }

  const failure = {
    decision: failOpen ? "allow" : "block",
    reason,
    kind: result?.kind || "tool-failure",
    toolFailure: true
  };
  return failure;
}
