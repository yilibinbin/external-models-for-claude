import { redactMachinePaths } from "./path-hygiene.mjs";

// Secret shapes worth redacting from Codex-derived text before it is persisted
// to job state and re-displayed (e.g. in /codex:status and /codex:result).
const SECRET_PATTERNS = [
  /\bAKIA[0-9A-Z]{16}\b/g,
  /\bAIza[0-9A-Za-z_-]{35}\b/g,
  /\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z_]{20,}\b/g,
  /\bsk-[A-Za-z0-9_-]{20,}\b/g,
  // JSON / quoted key:value form. The value class consumes backslash escapes so
  // an embedded escaped quote does not end the value early and leak its suffix.
  /(["'`]?\b(?:api[_-]?key|token|secret|password|passwd|pwd)\b["'`]?\s*[:=]\s*)(["'`])(?:\\.|(?!\2)[^\\])+\2/gi,
  // bare (unquoted) key=value form; the negative lookahead keeps it idempotent.
  /\b(?:api[_-]?key|token|secret|password|passwd|pwd)\s*[:=]\s*(?!\[secret\](?:[\s"'`,}\]]|$))[^\s"'`,}]+/gi
];

const ANSI_PATTERN = /\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])/g;
const CONTROL_PATTERN = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g;

export function stripTerminalControls(text) {
  return String(text ?? "").replace(ANSI_PATTERN, "").replace(CONTROL_PATTERN, "");
}

export function redactSecrets(text) {
  let output = String(text ?? "");
  for (const pattern of SECRET_PATTERNS) {
    output = output.replace(pattern, (match, keyPrefix) =>
      typeof keyPrefix === "string" ? `${keyPrefix}[secret]` : "[secret]"
    );
  }
  return output;
}

// Redact secrets + local machine paths + terminal control chars from a piece of
// Codex-derived text (a summary line or model output) before it is persisted or
// shown to the user. Local-path redaction reuses the existing path-hygiene regex.
export function sanitizeModelText(text) {
  return redactMachinePaths(redactSecrets(stripTerminalControls(text)));
}
