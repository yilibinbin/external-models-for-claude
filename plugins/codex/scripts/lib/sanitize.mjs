import { redactMachinePaths } from "./path-hygiene.mjs";

// Secret shapes worth redacting from Codex-derived text before it is persisted
// to job state and re-displayed (e.g. in /codex:status and /codex:result).
const SECRET_PATTERNS = [
  /\bAKIA[0-9A-Z]{16}\b/g,
  /\bAIza[0-9A-Za-z_-]{35}\b/g,
  /\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z_]{20,}\b/g,
  /\bsk-[A-Za-z0-9_-]{20,}\b/g
];

// Key names whose assigned value is a credential, normalized to letters+digits
// so one entry covers API_KEY / api-key / apiKey alike.
//
// Deciding this in JS rather than in the regex is load-bearing, not a style
// choice. Every regex formulation that scans the key name needs a bounded
// prefix to stay linear, and a bounded prefix anchored by a lookbehind fails
// SILENTLY once the key outgrows the bound: no start position satisfies the
// lookbehind, so no match is attempted at all. Measured on the rejected
// candidate `(?<![\w.-])[\w.-]{0,64}(?:...)`: matched at a 60-char key, total
// bypass at 64 and beyond -- squarely where deeply-namespaced enterprise names
// like ACME_PLATFORM_INTERNAL_SERVICE_API_KEY live. Raising the bound only
// moves the cliff. A substring test has no cliff at any length.
const SENSITIVE_KEY_FRAGMENTS = [
  "apikey",
  "token",
  "secret",
  "password",
  "passwd",
  "passphrase",
  "pwd",
  "credential",
  "privatekey",
  "accesskey",
  "cookie",
  "databaseurl",
  "dburl",
  "connectionstring",
  "authorization",
  "signature"
];

// Assignments are found by scanning for the SEPARATOR and looking back for the
// key, rather than by matching key-separator-value as one unit.
//
// A single combined pattern is wrong here: in `rpc failed: DATABASE_URL=pg://u:pw@h`
// the key `failed` matches first and consumes `DATABASE_URL=pg://u:pw@h` as its
// value, so the real assignment nested inside is never examined and the
// credential survives. Scanning separators examines every `:`/`=` on its own
// terms, so a non-sensitive assignment cannot swallow a sensitive one.
const SEPARATOR_SCAN = /\s*[:=]\s*/g;
const KEY_TAIL = /[\w.-]+$/;
// The quoted value class consumes backslash escapes so an embedded escaped quote
// cannot end the value early and leak its suffix. The bare class admits `]` so
// an already-redacted `[secret]` is read whole (see isRedactedValue).
const QUOTED_VALUE = /^(["'`])((?:\\.|(?!\1)[^\\])*)\1/;
const BARE_VALUE = /^[^\s"'`,}]+/;

const REDACTED = "[secret]";

function isSensitiveKey(key) {
  const normalized = String(key).toLowerCase().replace(/[^a-z0-9]/g, "");
  return SENSITIVE_KEY_FRAGMENTS.some((fragment) => normalized.includes(fragment));
}

// Keeps redaction idempotent: `summary` is now sanitized at the job-state
// chokepoint on top of call sites that already sanitize, so a second pass must
// be a no-op rather than nesting markers.
function isRedactedValue(value) {
  return value === REDACTED;
}

const ANSI_PATTERN = /\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])/g;
const CONTROL_PATTERN = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g;

export function stripTerminalControls(text) {
  return String(text ?? "").replace(ANSI_PATTERN, "").replace(CONTROL_PATTERN, "");
}

export function redactSecrets(text) {
  let output = String(text ?? "");
  for (const pattern of SECRET_PATTERNS) {
    output = output.replace(pattern, REDACTED);
  }
  return redactAssignedValues(output);
}

// The key name is preserved and only the value is dropped. A review whose point
// is "line 12 commits AWS_SECRET_ACCESS_KEY" stays actionable -- the reader
// already holds the value; what they need is which key, and where.
function redactAssignedValues(text) {
  const pieces = [];
  let copiedThrough = 0;
  SEPARATOR_SCAN.lastIndex = 0;

  for (let match = SEPARATOR_SCAN.exec(text); match; match = SEPARATOR_SCAN.exec(text)) {
    const separatorEnd = match.index + match[0].length;
    // Skip separators already inside a redacted region rather than reinterpreting
    // the text we just rewrote.
    if (match.index < copiedThrough) {
      continue;
    }

    const key = KEY_TAIL.exec(text.slice(copiedThrough, match.index))?.[0];
    if (!key || !isSensitiveKey(key)) {
      continue;
    }

    const rest = text.slice(separatorEnd);
    const quoted = QUOTED_VALUE.exec(rest);
    const value = quoted ? quoted[2] : BARE_VALUE.exec(rest)?.[0];
    if (value === undefined || isRedactedValue(value)) {
      continue;
    }

    const quote = quoted ? quoted[1] : "";
    pieces.push(text.slice(copiedThrough, separatorEnd), `${quote}${REDACTED}${quote}`);
    copiedThrough = separatorEnd + (quoted ? quoted[0].length : value.length);
    SEPARATOR_SCAN.lastIndex = copiedThrough;
  }

  pieces.push(text.slice(copiedThrough));
  return pieces.join("");
}

// Redact secrets + local machine paths + terminal control chars from a piece of
// Codex-derived text (a summary line or model output) before it is persisted or
// shown to the user. Local-path redaction reuses the existing path-hygiene regex.
export function sanitizeModelText(text) {
  return redactMachinePaths(redactSecrets(stripTerminalControls(text)));
}
