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
// Sticky, so the value is read at an index without slicing the remainder. The
// quoted class consumes backslash escapes so an embedded escaped quote cannot
// end the value early and leak its suffix; the bare class admits `]` so an
// already-redacted `[secret]` is read whole (see isRedactedValue).
const QUOTED_VALUE = /(["'`])((?:\\.|(?!\1)[^\\])*)\1/y;
const BARE_VALUE = /[^\s"'`,}]+/y;
const QUOTE_CHARS = new Set(['"', "'", "`"]);
const KEY_CHAR = /[\w.-]/;
// Keys whose value runs to the end of the line rather than to the next space.
// Redacting only the first token yielded `Authorization: [secret] eyJhbGci...`
// -- worse than doing nothing, because it reads as already handled. Keyed on the
// header NAME rather than on a list of schemes: enumerating schemes missed
// Negotiate and NTLM, and a cookie header holds several pairs.
const LINE_VALUED_KEYS = ["authorization", "cookie", "setcookie"];
// PEM bodies are newline-delimited, so the line rule above would keep all but
// the first line. Consume through the matching end marker instead.
const PEM_BEGIN = /^-----BEGIN [A-Z ]*-----/;
const PEM_END = /-----END [A-Z ]*-----/;

const REDACTED = "[secret]";

function isLineValuedKey(key) {
  const normalized = String(key).toLowerCase().replace(/[^a-z0-9]/g, "");
  return LINE_VALUED_KEYS.some((name) => normalized.endsWith(name));
}

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

// Reads the key ending at `end`, walking backwards over key characters and, if
// the key is quoted (`{"password": ...}`), over the surrounding quotes.
//
// The backward walk is bounded by the key's own length, so total work stays
// linear in the input. Slicing the text before each separator instead was
// measurably quadratic -- 20/80/160 KB of ordinary `status=ok` pairs took
// 96/1465/6032 ms -- because every separator re-scanned an ever-growing prefix.
function readKeyBefore(text, end, floor) {
  let cursor = end;
  while (cursor > floor && /\s/.test(text[cursor - 1])) {
    cursor -= 1;
  }
  const closingQuote = cursor > floor && QUOTE_CHARS.has(text[cursor - 1]) ? text[cursor - 1] : "";
  if (closingQuote) {
    cursor -= 1;
  }
  const keyEnd = cursor;
  while (cursor > floor && KEY_CHAR.test(text[cursor - 1])) {
    cursor -= 1;
  }
  if (cursor === keyEnd) {
    return null;
  }
  if (closingQuote && !(cursor > floor && text[cursor - 1] === closingQuote)) {
    return null;
  }
  return text.slice(cursor, keyEnd);
}

function spanTo(text, index, end) {
  return { value: text.slice(index, end), quote: "", length: end - index };
}

function readValueAt(text, index, key) {
  QUOTED_VALUE.lastIndex = index;
  const quoted = QUOTED_VALUE.exec(text);
  if (quoted) {
    return { value: quoted[2], quote: quoted[1], length: quoted[0].length };
  }

  const rest = text.slice(index, index + 32);
  if (PEM_BEGIN.test(rest)) {
    const endMarker = PEM_END.exec(text.slice(index));
    if (endMarker) {
      return spanTo(text, index, index + endMarker.index + endMarker[0].length);
    }
    // Unterminated PEM: fail closed and take the remainder rather than leak it.
    return spanTo(text, index, text.length);
  }

  if (isLineValuedKey(key)) {
    const lineEnd = text.indexOf("\n", index);
    return spanTo(text, index, lineEnd === -1 ? text.length : lineEnd);
  }

  BARE_VALUE.lastIndex = index;
  const bare = BARE_VALUE.exec(text);
  return bare ? { value: bare[0], quote: "", length: bare[0].length } : null;
}

// The key name is preserved and only the value is dropped. A review whose point
// is "line 12 commits AWS_SECRET_ACCESS_KEY" stays actionable -- the reader
// already holds the value; what they need is which key, and where.
function redactAssignedValues(text) {
  const pieces = [];
  let copiedThrough = 0;
  SEPARATOR_SCAN.lastIndex = 0;

  for (let match = SEPARATOR_SCAN.exec(text); match; match = SEPARATOR_SCAN.exec(text)) {
    // Skip separators already inside a redacted region rather than
    // reinterpreting text this pass just rewrote.
    if (match.index < copiedThrough) {
      continue;
    }

    const key = readKeyBefore(text, match.index, copiedThrough);
    if (!key || !isSensitiveKey(key)) {
      continue;
    }

    const separatorEnd = match.index + match[0].length;
    const found = readValueAt(text, separatorEnd, key);
    if (!found || isRedactedValue(found.value)) {
      continue;
    }

    pieces.push(text.slice(copiedThrough, separatorEnd), `${found.quote}${REDACTED}${found.quote}`);
    copiedThrough = separatorEnd + found.length;
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
