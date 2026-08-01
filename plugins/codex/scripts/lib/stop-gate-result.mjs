import { sanitizeModelText } from "./sanitize.mjs";

// The reason is model-authored and ends up in the Claude transcript, which is
// permanent and outside this plugin's control. Redaction keeps the finding and
// drops the credential: the sanitizer preserves the key name and the location
// and replaces only the value, so "src/config.ts:12 commits FOO_TOKEN=..."
// stays actionable without carrying the secret into the transcript.
//
// All three return shapes reference this one binding, so wrapping it here
// covers every classifier outcome. It does NOT cover handleHookException, which
// never calls this function -- that is why emitHookDecision redacts as well.
export function classifyStopGateResult(result, options = {}) {
  const failOpen = Boolean(options.failOpen);
  const reason =
    sanitizeModelText(String(result?.reason || "").trim()) ||
    "Codex stop review gate did not return a reason.";
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
