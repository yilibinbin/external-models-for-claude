import os from "node:os";
import path from "node:path";
import { canonicalWorkspaceRoot } from "./state.mjs";

const SECRET_PATTERNS = [
  // A URI with inline credentials is a secret whatever the variable is called
  // (DATABASE_URL, REDIS_URL, ...) -- keying on the name alone cannot keep up
  // with every connection-string env var a project might invent, and naming
  // more would also catch BASE_URL, an ordinary endpoint. Ported from the
  // hardened codex sanitizer (plugins/codex/scripts/lib/sanitize.mjs), which
  // measured this exact scheme-bounded, non-quadratic shape as safe.
  /(?<![a-z0-9+.-])[a-z][a-z0-9+.-]{0,31}:\/\/[^\s:@/]*:[^\s@/]+@[^\s"'`,}]*/gi,
  /\bAKIA[0-9A-Z]{16}\b/g,
  /\bAIza[0-9A-Za-z_-]{35}\b/g,
  /\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z_]{20,}\b/g,
  /\bsk-[A-Za-z0-9_-]{20,}\b/g
];

// Key names whose value is a credential, matched per SEGMENT rather than as a
// keyword immediately adjacent to `:`/`=`. The prior single regex required the
// keyword to sit right before the separator, so any compound identifier
// (AWS_SECRET_ACCESS_KEY, STRIPE_SECRET_KEY, DB_PASSWORD) matched nothing at
// all. Segment-based matching is ported from the codex sanitizer's key-segment
// scanner, scoped down to exact-segment membership only (no qualifier/suffix
// pairing) since every confirmed compound-name gap here is closed by a plain
// segment already on this list.
const STRONG_KEY_SEGMENTS = new Set([
  "apikey",
  "token",
  "secret",
  "secrets",
  "password",
  "passwd",
  "passphrase",
  "pwd",
  "credential",
  "credentials",
  "cookie",
  "bearer",
  "privatekey"
]);

// Segments that make an otherwise-matching key NON-sensitive: `token_count` is
// a number and `session_status` an enum, both ordinary diagnostics. Checked
// first so it demotes the whole key, matching the codex sanitizer this was
// ported from -- without it, moving from adjacency-only matching to segment
// matching would turn these into NEW false positives the old regex never had
// (the old pattern required the keyword immediately before `:`/`=`, and
// "count"/"status" always sits in between).
const NON_SECRET_SEGMENTS = new Set(["count", "length", "size", "status", "state", "enabled", "disabled", "name"]);

function keySegments(key) {
  return String(key)
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

export function isSensitiveKey(key) {
  const segments = keySegments(key);
  if (segments.length > 1 && NON_SECRET_SEGMENTS.has(segments[segments.length - 1])) {
    return false;
  }
  if (segments.some((segment) => STRONG_KEY_SEGMENTS.has(segment))) {
    return true;
  }
  // api_key / API-Key / ApiKey: "api" and "key" split into two segments on any
  // separator or camelCase boundary, and neither is sensitive alone ("key" by
  // itself is too broad -- PRIMARY_KEY, DICT_KEYS -- so only this specific
  // adjacent pair counts). "apikey" with no separator is caught above as one
  // segment already in STRONG_KEY_SEGMENTS.
  for (let index = 0; index < segments.length - 1; index += 1) {
    if (segments[index] === "api" && segments[index + 1] === "key") {
      return true;
    }
  }
  return false;
}

const SEPARATOR_SCAN = /[:=]\s*/g;
const KEY_CHAR = /[\w.-]/;
const BARE_VALUE = /[^\s"'`]+/y;
// Ported from the codex sanitizer: the captured group consumes backslash
// escapes (`\\.`), so an embedded escaped quote does not end the value early
// -- `password: "hu\"nter2"` is one value, not a truncated one that leaves
// `nter2"` in the clear behind a marker that reads as complete.
const QUOTED_VALUE = /(["'`])((?:\\.|(?!\1)[^\\])*)\1/y;

// Bounded by the key's own length: the walk stops at the first character that
// is not a key character, and the separator/prior walk's stop point is never
// itself a key character, so no walk can re-cross ground a prior walk covered.
function readKeyBefore(text, end) {
  let cursor = end;
  while (cursor > 0 && /\s/.test(text[cursor - 1])) {
    cursor -= 1;
  }
  const keyEnd = cursor;
  while (cursor > 0 && KEY_CHAR.test(text[cursor - 1])) {
    cursor -= 1;
  }
  return cursor === keyEnd ? null : text.slice(cursor, keyEnd);
}

const QUOTE_CHARS = new Set(['"', "'", "`"]);

// A quoted value (`password: "hunter2"`) first, since BARE_VALUE's excluded-
// quote-character class can never start a match on the opening quote itself
// -- without this, any quoted assignment silently fell through unredacted.
// The quote characters are kept around the marker so quoted-value syntax
// stays intact (`"[secret]"`, not a bare `[secret]` where a string was
// expected).
function readValueAt(text, index) {
  QUOTED_VALUE.lastIndex = index;
  const quoted = QUOTED_VALUE.exec(text);
  if (quoted) {
    return { length: quoted[0].length, redacted: `${quoted[1]}[secret]${quoted[1]}`, alreadyRedacted: quoted[2] === "[secret]" };
  }
  // An opening quote with no closing delimiter -- QUOTED_VALUE cannot match
  // (it requires a balanced pair) and BARE_VALUE cannot start ON a quote
  // either, so an unterminated quoted value fell through both rules
  // completely unredacted. This is exactly the shape a truncated/malformed
  // model response produces. Fail closed on the remainder: the value opened
  // and never closed, so everything after it is plausibly the value.
  if (QUOTE_CHARS.has(text[index])) {
    return { length: text.length - index, redacted: "[secret]", alreadyRedacted: false };
  }
  BARE_VALUE.lastIndex = index;
  const bare = BARE_VALUE.exec(text);
  if (!bare) {
    return null;
  }
  return { length: bare[0].length, redacted: "[secret]", alreadyRedacted: bare[0] === "[secret]" };
}

// Scans for the SEPARATOR and looks back for the key, rather than matching
// key-separator-value as one combined pattern -- see readKeyBefore for why.
// The key name is preserved and only the value replaced, so a review quoting
// "line 12 commits AWS_SECRET_ACCESS_KEY" stays actionable.
function redactAssignedValues(text) {
  const pieces = [];
  let copiedThrough = 0;
  SEPARATOR_SCAN.lastIndex = 0;
  for (let match = SEPARATOR_SCAN.exec(text); match; match = SEPARATOR_SCAN.exec(text)) {
    if (match.index < copiedThrough) {
      continue;
    }
    const key = readKeyBefore(text, match.index);
    if (!key || !isSensitiveKey(key)) {
      continue;
    }
    const separatorEnd = match.index + match[0].length;
    const found = readValueAt(text, separatorEnd);
    if (!found || found.alreadyRedacted) {
      continue;
    }
    pieces.push(text.slice(copiedThrough, separatorEnd), found.redacted);
    copiedThrough = separatorEnd + found.length;
    SEPARATOR_SCAN.lastIndex = copiedThrough;
  }
  pieces.push(text.slice(copiedThrough));
  return pieces.join("");
}

const ANSI_PATTERN = /\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])/g;
const CONTROL_PATTERN = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g;

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function capUtf8(text, maxBytes) {
  const limit = Number.isInteger(maxBytes) && maxBytes > 0 ? maxBytes : 2048;
  if (Buffer.byteLength(text, "utf8") <= limit) {
    return text;
  }
  const marker = " [truncated]";
  const markerBytes = Buffer.byteLength(marker, "utf8");
  let output = "";
  for (const char of text) {
    if (Buffer.byteLength(output + char, "utf8") + markerBytes > limit) {
      break;
    }
    output += char;
  }
  return `${output}${marker}`;
}

export function stripTerminalControls(text) {
  return String(text ?? "").replace(ANSI_PATTERN, "").replace(CONTROL_PATTERN, "");
}

export function redactSecrets(text) {
  let output = String(text ?? "");
  for (const pattern of SECRET_PATTERNS) {
    output = output.replace(pattern, "[secret]");
  }
  return redactAssignedValues(output);
}

export function redactLocalPaths(text, { cwd = process.cwd(), env = process.env } = {}) {
  let output = String(text ?? "");
  const replacements = new Set();
  for (const candidate of [env.HOME, os.homedir(), canonicalWorkspaceRoot(cwd, env)]) {
    if (candidate) {
      replacements.add(path.resolve(candidate));
    }
  }
  for (const candidate of replacements) {
    output = output.replace(new RegExp(`${escapeRegExp(candidate)}(?:[/\\\\][^\\s"'<>]*)?`, "g"), "[local-path]");
  }
  output = output.replace(/\/Users\/[A-Za-z0-9._-]+(?:\/[^\s"'<>]*)?/g, "[local-path]");
  output = output.replace(/\/home\/[A-Za-z0-9._-]+(?:\/[^\s"'<>]*)?/g, "[local-path]");
  output = output.replace(/\/private\/var\/folders(?:\/[^\s"'<>]*)?/g, "[local-path]");
  output = output.replace(/\/var\/folders(?:\/[^\s"'<>]*)?/g, "[local-path]");
  output = output.replace(/\/private\/tmp(?:\/[^\s"'<>]*)?/g, "[local-path]");
  output = output.replace(/\/tmp(?:\/[^\s"'<>]*)?/g, "[local-path]");
  output = output.replace(/[A-Za-z]:\\Users\\[A-Za-z0-9._-]+(?:\\[^\s"'<>]*)?/g, "[local-path]");
  output = output.replace(/\\\\[A-Za-z0-9._-]+\\[A-Za-z0-9._-]+(?:\\[^\s"'<>]*)?/g, "[local-path]");
  return output;
}

export function sanitizeSummary(text, options = {}) {
  const stripped = stripTerminalControls(text);
  const redacted = redactLocalPaths(redactSecrets(stripped), options);
  return capUtf8(redacted, options.maxBytes ?? 2048);
}

// Sanitizing raw text BEFORE it is parsed as JSON is unsafe: a redacted span
// can consume a backslash that was escaping a quote inside a JSON string
// value, turning `\"` into a bare `"` that then prematurely terminates the
// string and breaks JSON.parse for the caller. Sanitizing after parsing,
// walking only the decoded string leaves, cannot corrupt structure that no
// longer exists as text -- there is nothing left to mis-escape.
// Codex's stage-2 review of an earlier version of this function found it
// blind to the JSON key: walking `{"password": "hunter2"}` called
// sanitizeFn("hunter2") with no idea it came from a "password" field, and
// "hunter2" alone has no key=value SHAPE and matches no secret pattern, so it
// passed through untouched -- only a string that happened to embed its own
// "key=value" text (e.g. an "evidence" field's prose) was ever caught. A
// string under a key that is itself sensitive (per the same isSensitiveKey
// used by redactAssignedValues) is now replaced outright, independent of
// whatever shape the value has.
export function deepSanitizeStrings(value, sanitizeFn, keyHint) {
  // Checked BEFORE dispatching on type, and short-circuits without
  // recursing further: a value that is itself checked only inside the
  // string branch left a composite value under a sensitive key untouched --
  // `{password: {value: "hunter2"}}` recursed into the object with the
  // INNER key "value" (not sensitive) replacing the outer "password" as the
  // keyHint, so the nested string was checked against the wrong key and the
  // whole-value guarantee this function claims did not actually hold for
  // anything but a bare string. Numbers/booleans/null are excluded: they
  // cannot carry secret-shaped text, and replacing one with the string
  // "[secret]" would be a type change with no security benefit.
  const isTextLike = typeof value === "string" || Array.isArray(value) || (value !== null && typeof value === "object");
  if (keyHint !== undefined && isTextLike && isSensitiveKey(keyHint)) {
    return "[secret]";
  }
  if (typeof value === "string") {
    return sanitizeFn(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => deepSanitizeStrings(item, sanitizeFn, keyHint));
  }
  if (value && typeof value === "object") {
    const out = {};
    for (const [key, entry] of Object.entries(value)) {
      // Object.defineProperty, not out[key] = ...: this walks an UNTRUSTED
      // parsed object, and a key literally named "__proto__" makes a plain
      // bracket assignment invoke Object.prototype's __proto__ accessor
      // setter instead of creating a literal own property -- reassigning
      // `out`'s own prototype to whatever (sanitized) value that key held,
      // rather than storing it under that name. defineProperty always
      // creates a literal own data property regardless of the key's name.
      Object.defineProperty(out, key, {
        value: deepSanitizeStrings(entry, sanitizeFn, key),
        writable: true,
        enumerable: true,
        configurable: true
      });
    }
    return out;
  }
  return value;
}
