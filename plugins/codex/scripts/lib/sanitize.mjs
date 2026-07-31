import { redactMachinePaths } from "./path-hygiene.mjs";

// Secret shapes worth redacting from Codex-derived text before it is persisted
// to job state and re-displayed (e.g. in /codex:status and /codex:result).
const SECRET_PATTERNS = [
  /\bAKIA[0-9A-Z]{16}\b/g,
  /\bAIza[0-9A-Za-z_-]{35}\b/g,
  /\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z_]{20,}\b/g,
  /\bsk-[A-Za-z0-9_-]{20,}\b/g,
  // `Authorization: Bearer <token>` / `Proxy-Authorization: Basic <blob>` — a header
  // shape with no `key=value` structure, so the patterns below cannot see it. The
  // optional quotes cover the JSON form `{"Authorization":"Bearer …"}`, where the
  // scheme does not sit directly against the colon.
  /(["'`]?\b(?:proxy-)?authorization["'`]?\s*[:=]\s*)["'`]?(?:bearer|basic|token)\s+[^\s"'`,}]+["'`]?/gi,
  // JSON / quoted key:value form. The value class consumes backslash escapes so
  // an embedded escaped quote does not end the value early and leak its suffix.
  /(["'`]?[\w.-]*(?:api[_-]?key|token|secret|password|passwd|pwd|credential)[\w.-]*["'`]?\s*[:=]\s*)(["'`])(?:\\.|(?!\2)[^\\])+\2/gi,
  // Same key, but with an UNTERMINATED quote — truncated output (a tail cut, a killed
  // writer) routinely produces `TOKEN="value` with no closing quote, which the
  // balanced-quote pattern above cannot match and the bare pattern below skips because
  // its value class excludes the quote character.
  // The lookahead must reference the CAPTURED opening delimiter, not "any quote":
  // `TOKEN="abc'def` is unterminated despite containing an apostrophe, and rejecting
  // on any quote character left exactly those mixed-quote values visible.
  /([\w.-]*(?:api[_-]?key|token|secret|password|passwd|pwd|credential)[\w.-]*\s*[:=]\s*)(["'`])(?!(?:\\.|[^\\\n])*?\2)[^\n]+/gi,
  // bare (unquoted) key=value form; the negative lookahead keeps it idempotent.
  //
  // The keyword is allowed to sit inside a longer identifier ([\w.-] on both sides)
  // because real credentials almost never appear as the bare word: the shapes that
  // matter are AWS_SECRET_ACCESS_KEY, GITHUB_TOKEN, DATABASE_PASSWORD, db.password.
  // A `\b`-anchored keyword with `=` required immediately after missed all of them.
  /[\w.-]*(?:api[_-]?key|token|secret|password|passwd|pwd|credential)[\w.-]*\s*[:=]\s*(?!\[secret\](?:[\s"'`,}\]]|$))[^\s"'`,}]+/gi
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
