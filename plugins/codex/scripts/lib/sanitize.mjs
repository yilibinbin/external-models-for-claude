// BEST-EFFORT REDACTION. Read this before relying on it.
//
// This module recognises credential SHAPES. Its coverage is therefore
// enumerable, and an enumerable list is never complete: adversarial review of
// this file found new bypasses in FIVE consecutive rounds -- long key names,
// quoted keys, auth schemes it had not listed, unterminated quotes, structured
// values, braces inside strings, PEM headers longer than the window it
// inspected, forged `[secret]` markers, keys containing spaces. Each was real
// and each was fixed; the point is that the sequence did not end because it
// cannot.
//
// Threat model, stated so the limits are judged against the right bar: this
// defends against ACCIDENTAL exposure -- a review quoting a config file, a
// stack trace carrying an env dump. It does NOT defend against a producer
// deliberately shaping output to evade it. Nothing shape-based can.
//
// So it must never be the ONLY thing standing between child output and a sink.
// Where a structural bound exists, that bound is the defence and this is a
// second layer: the raw stderr payload field is deleted rather than redacted,
// the rendered fence is gated on failure rather than scrubbed, stderr is never
// returned as the answer, and job state is written 0600.
//
// The channels that have no structural backstop -- the job `summary`, progress
// lines, the stop-gate reason -- are the ones where this file's limits are the
// system's limits. Treat a new bypass there as expected, not as a surprise.
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
// COMPOUND names only. Single words moved to STRONG_KEY_SEGMENTS below, because
// a substring test on them flags ordinary identifiers: `token` matches
// `tokenizer_model`, `cookie` matches `cookie_domain`. With unquoted values
// running to end-of-line, each false positive erases the rest of its line.
const SENSITIVE_KEY_FRAGMENTS = [
  "apikey",
  "privatekey",
  "accesskey",
  "databaseurl",
  "dburl",
  "connectionstring",
  "connectionuri",
  "redisurl",
  "postgresurl",
  "postgresqlurl",
  "mysqlurl",
  "mongodburi",
  "mongourl",
  "amqpurl",
  "dockerauth",
  "npmconfigauth",
  "registryauth",
  "authconfig"
];


// Assignments are found by scanning for the SEPARATOR and looking back for the
// key, rather than by matching key-separator-value as one unit.
//
// A single combined pattern is wrong here: in `rpc failed: DATABASE_URL=pg://u:pw@h`
// the key `failed` matches first and consumes `DATABASE_URL=pg://u:pw@h` as its
// value, so the real assignment nested inside is never examined and the
// credential survives. Scanning separators examines every `:`/`=` on its own
// terms, so a non-sensitive assignment cannot swallow a sensitive one.
// No leading `\s*`. A greedy whitespace prefix retries at every position inside
// a whitespace run, which measured 55/834/3369 ms for 10k/40k/80k spaces -- the
// THIRD distinct quadratic found in this file, and this one can wedge the
// fail-closed stop gate, which sanitizes before it bounds. Leading whitespace is
// already skipped walking backwards in readKeyBefore, so dropping it here costs
// nothing.
const SEPARATOR_SCAN = /[:=]\s*/g;
// Sticky, so the value is read at an index without slicing the remainder. The
// quoted class consumes backslash escapes so an embedded escaped quote cannot
// end the value early and leak its suffix; the bare class admits `]` so an
// already-redacted `[secret]` is read whole (see isRedactedValue).
const QUOTED_VALUE = /(["'`])((?:\\.|(?!\1)[^\\])*)\1/y;
const BARE_VALUE = /[^\s"'`,}]+/y;
const QUOTE_CHARS = new Set(['"', "'", "`"]);
const KEY_CHAR = /[\w.-]/;
// PEM bodies are newline-delimited, so the line rule above would keep all but
// the first line. Consume through the matching end marker instead.
const PEM_END = /-----END [A-Z ]*-----/;
// An `-----END` marker with no `-----BEGIN` before it means the body arrived
// without its header -- which is what a truncated capture produces. Those lines
// carry no key and no marker, so nothing else in this file can recognise them.
const ORPHAN_PEM_END = /-----END [A-Z ]*-----/;

const REDACTED = "[secret]";


// Single-word segments that make a key sensitive. Matched per SEGMENT, not as a
// substring of the whole key, because the short ones are substrings of ordinary
// words: `key` is in `keyboard`, `auth` is in `author`, `pass` is in
// `tests_passed`. Splitting on separators and camelCase boundaries first gives
// SSH_KEY / AUTH_HEADER / DB_PASS without eating any of those.
// A bare `key` / `pass` / `auth` segment is NOT enough: PRIMARY_KEY, FOREIGN_KEY,
// PASS_RATE and DICT_KEYS are ordinary identifiers, and with unquoted values now
// running to end-of-line, a false positive destroys the rest of the line.
//
// So a weak word only counts when a QUALIFIER precedes it. That keeps SSH_KEY,
// DB_PASS, AUTH_HEADER, ENCRYPTION_KEY, CLIENT_KEY, TLSCert, JWTAuth while
// leaving the identifiers above alone.
const STRONG_KEY_SEGMENTS = new Set([
  "token",
  "authorization",
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
  "signature",
  "apikey",
  "privatekey"
]);


const KEY_QUALIFIERS = new Set([
  "ssh",
  "tls",
  "ssl",
  "api",
  "private",
  "public",
  "secret",
  "client",
  "encryption",
  "signing",
  "access",
  "db",
  "database",
  "jwt",
  "auth",
  "oauth",
  "bearer",
  "session",
  "refresh",
  "master",
  "service",
  "account"
]);

const WEAK_KEY_SEGMENTS = new Set([
  "key",
  // SESSION_ID / REFRESH_ID are credentials; REQUEST_ID / JOB_ID are not, and
  // their first segment is not a qualifier, so pairing keeps them apart.
  "id",
  "keys",
  "pass",
  "cert",
  "certificate",
  "auth",
  "header",
  "token",
  "credential"
]);

function keySegments(key) {
  return String(key)
    // lowerUpper AND ACRONYMWord: `SSHKey` / `DBPass` / `JWTAuth` / `TLSCert`
    // split on neither rule without the second, so every acronym-prefixed
    // credential name passed through as one unrecognised segment.
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

// Segments that make a key NON-sensitive despite an otherwise matching shape.
// `token_count` is a number, `passwordless` is a boolean, `signature_status` is
// an enum, and `SSH_AUTH_SOCK` is a socket path -- all ordinary diagnostics, and
// with unquoted values running to end-of-line a false positive here erases the
// rest of the line.
const NON_SECRET_SEGMENTS = new Set([
  "count",
  "length",
  "size",
  "status",
  "state",
  "enabled",
  "disabled",
  "sock",
  "socket",
  "path",
  "file",
  "dir",
  "type",
  "kind",
  "version",
  "expiry",
  "expires",
  "ttl",
  "domain",
  "name",
  "model",
  "prefix",
  "suffix",
  "format",
  "encoding"
]);


function isSensitiveKey(key) {
  const segments = keySegments(key);
  // A trailing qualifier of shape rather than of secrecy demotes the whole key.
  if (segments.length > 1 && NON_SECRET_SEGMENTS.has(segments[segments.length - 1])) {
    return false;
  }
  // `passwordless` is one segment and must not match `password` as a substring.
  if (segments.length === 1 && /less$/.test(segments[0])) {
    return false;
  }
  const normalized = String(key).toLowerCase().replace(/[^a-z0-9]/g, "");
  if (SENSITIVE_KEY_FRAGMENTS.some((fragment) => normalized.includes(fragment))) {
    return true;
  }
  if (segments.some((segment) => STRONG_KEY_SEGMENTS.has(segment))) {
    return true;
  }
  return segments.some(
    (segment, index) => index > 0 && KEY_QUALIFIERS.has(segments[index - 1]) && WEAK_KEY_SEGMENTS.has(segment)
  );
}

// Keeps redaction idempotent: `summary` is now sanitized at the job-state
// chokepoint on top of call sites that already sanitize, so a second pass must
// be a no-op rather than nesting markers.
function isRedactedValue(text, value, endIndex) {
  if (value !== REDACTED) {
    return false;
  }
  // The marker must be the WHOLE value. `API_KEY=[secret]leftover` otherwise
  // skipped the assignment as already-handled and left `leftover` in place --
  // which is also what a chunk boundary produces when a partial value is
  // redacted and its remainder arrives in the next event.
  // A space after the marker is NOT proof the value ended: compaction can turn
  // `Authorization: Bearer <jwt>` into `Authorization: [secret] <jwt>` and the
  // JWT then arrives looking like separate prose. Only a line break or a
  // structural delimiter closes the value.
  const rest = text.slice(endIndex);
  return rest === "" || /^[\r\n"'`,;}\]]/.test(rest);
}

const ANSI_PATTERN = /\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])/g;
const CONTROL_PATTERN = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g;

export function stripTerminalControls(text) {
  return String(text ?? "").replace(ANSI_PATTERN, "").replace(CONTROL_PATTERN, "");
}

const PEM_BLOCK = /-----BEGIN [A-Z0-9 ]*-----[\s\S]*?-----END [A-Z0-9 ]*-----/g;

export function redactSecrets(text) {
  let output = String(text ?? "");
  for (const pattern of SECRET_PATTERNS) {
    output = output.replace(pattern, REDACTED);
  }
  // A whole PEM block is a credential on its own. Everything else here keys off
  // an assignment, so a bare block -- which is exactly how a key is pasted into
  // a review or dumped by a tool -- passed through untouched.
  output = output.replace(PEM_BLOCK, REDACTED);
  return redactOrphanedKeyBody(redactAssignedValues(output));
}

// Key material whose BEGIN header was cut away by capture truncation. The body
// lines carry no key name and no marker, so the assignment scanner cannot see
// them; the closing marker is the only evidence left that they are key material.
function redactOrphanedKeyBody(text) {
  const end = ORPHAN_PEM_END.exec(text);
  if (!end) {
    return text;
  }
  const before = text.slice(0, end.index);
  if (before.includes("-----BEGIN")) {
    return text;
  }
  // Walk back over lines that LOOK like key body and stop at the first that does
  // not. Deleting everything before the marker instead destroyed up to a full
  // buffer of legitimate diagnostics, because a truncated key body is normally
  // preceded by ordinary output.
  const lines = before.split("\n");
  // Collect the trailing run of blank / marker / base64 lines, then require the
  // run to contain at least one FULL-WIDTH body line before deleting it.
  //
  // A uniform length floor was wrong in both directions: the last body line of a
  // PEM is a remainder and can be four characters, so the floor aborted the walk
  // at once and left the whole key; accepting any short base64 line instead
  // would delete ordinary short output.
  let firstBodyLine = lines.length;
  let seenNonEmpty = 0;
  while (firstBodyLine > 0) {
    const candidate = lines[firstBodyLine - 1];
    // A SHORT base64 line is only body when it sits immediately before the END
    // marker -- that is the remainder line of a real PEM. Anywhere else a short
    // alphanumeric run is ordinary prose: `diag` matches the base64 charset by
    // accident, and accepting it deleted the diagnostic line above the key.
    if (!looksLikeKeyBody(candidate, seenNonEmpty === 0)) {
      break;
    }
    if (candidate.trim()) {
      seenNonEmpty += 1;
    }
    firstBodyLine -= 1;
  }
  const collected = lines.slice(firstBodyLine);
  if (!collected.some((line) => line.trim().length >= 16 && /^[A-Za-z0-9+/=]+$/.test(line.trim()))) {
    // Nothing that looks like real key material precedes the marker.
    return text;
  }
  const head = lines.slice(0, firstBodyLine).join("\n");
  const tail = text.slice(end.index + end[0].length).replace(/^\n/, "");
  return `${head ? `${head}\n` : ""}${REDACTED}\n${tail}`;
}

// PEM body lines are unbroken base64 runs. A redaction marker counts too, so a
// body already collapsed by an earlier pass does not stop the walk.
// Blank lines, existing markers and base64 runs of ANY length. The "is this
// really key material" judgement is made on the collected run as a whole, not
// line by line -- see redactOrphanedKeyBody.
function looksLikeKeyBody(line, allowShort) {
  const trimmed = line.trim();
  if (!trimmed || trimmed === REDACTED || trimmed.endsWith(REDACTED)) {
    return true;
  }
  if (!/^[A-Za-z0-9+/=]+$/.test(trimmed)) {
    return false;
  }
  return trimmed.length >= 16 || allowShort;
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
  if (closingQuote) {
    // A quoted key may hold anything but its own quote -- `{"API KEY": ...}` is
    // ordinary JSON, and a KEY_CHAR-only scan stopped at the space and skipped
    // the assignment. Bounded to the line so this stays linear.
    while (cursor > floor && text[cursor - 1] !== closingQuote && text[cursor - 1] !== "\n") {
      cursor -= 1;
    }
    if (cursor === keyEnd || cursor === floor || text[cursor - 1] !== closingQuote) {
      return null;
    }
    return text.slice(cursor, keyEnd);
  }
  while (cursor > floor && KEY_CHAR.test(text[cursor - 1])) {
    cursor -= 1;
  }
  return cursor === keyEnd ? null : text.slice(cursor, keyEnd);
}

function spanTo(text, index, end) {
  return { value: text.slice(index, end), quote: "", length: end - index };
}

// Consumes a `{...}` / `[...]` value through its matching close, so a structured
// credential is taken whole. Without this the bare rule stopped at the first
// quote inside the braces and produced `credentials=[secret]"value":"TOPSECRET"}`
// -- redacted-looking, still leaking, and stable across a second pass.
function readBalancedValue(text, index) {
  const OPEN = { "{": "}", "[": "]" };
  const closer = OPEN[text[index]];
  if (!closer) {
    return null;
  }
  const opener = text[index];
  let depth = 0;
  let quote = "";
  for (let cursor = index; cursor < text.length; cursor += 1) {
    const char = text[cursor];
    // Braces inside a quoted string are data, not structure. Counting them
    // ended the value early: `credentials={"v":"TOP}SECRET"}` stopped at the
    // brace inside the string and left `SECRET"}` behind.
    if (quote) {
      if (char === "\\") {
        cursor += 1;
      } else if (char === quote) {
        quote = "";
      }
      continue;
    }
    if (QUOTE_CHARS.has(char)) {
      quote = char;
      continue;
    }
    if (char === opener) {
      depth += 1;
    } else if (char === closer) {
      depth -= 1;
      if (depth === 0) {
        return spanTo(text, index, cursor + 1);
      }
    }
  }
  // Unbalanced: fail closed on the remainder for the same reason an unterminated
  // quote does -- a line boundary is not the end of an unclosed structure.
  return spanTo(text, index, text.length);
}

function readValueAt(text, index, key) {
  QUOTED_VALUE.lastIndex = index;
  const quoted = QUOTED_VALUE.exec(text);
  if (quoted) {
    return { value: quoted[2], quote: quoted[1], length: quoted[0].length };
  }

  // An opening quote with no closing delimiter: the quoted rule cannot match and
  // the bare rule cannot START on a quote, so the value fell through untouched.
  // A truncated provider error is exactly this shape. Fail closed on the line.
  if (QUOTE_CHARS.has(text[index])) {
    // Unterminated quoted value. Stopping at the newline left the actual secret
    // on the FOLLOWING line while the output read as redacted, so fail closed on
    // the remainder: the value opened and never closed, so everything after it
    // is plausibly the value.
    return spanTo(text, index, text.length);
  }

  // Only accept a balanced span when it ENDS the value. `API_KEY=[secret]leftover`
  // otherwise parsed `[secret]` as the whole value, replaced it with `[secret]`
  // -- a no-op -- and left `leftover` in place, reading as redacted.
  const balanced = readBalancedValue(text, index);
  if (balanced) {
    // The terminator set must include the PARENT closers. Omitting `}`/`]`
    // rejected the correct span whenever a sensitive object or array was the
    // final child -- `{"credentials":{"value":"X"}}` fell back to the bare rule,
    // which replaced only the opening brace and left the contents behind a
    // marker that read as complete.
    const after = text[index + balanced.length];
    if (after === undefined || /[\s"'`,;}\]]/.test(after)) {
      return balanced;
    }
  }

  // Tested against the text directly rather than a fixed-width slice: a 32-char
  // window is shorter than `-----BEGIN ENCRYPTED PRIVATE KEY-----` and than the
  // OPENSSH header, so those fell through to the bare rule and leaked the body.
  if (text.startsWith("-----BEGIN", index)) {
    const endMarker = PEM_END.exec(text.slice(index));
    if (endMarker) {
      return spanTo(text, index, index + endMarker.index + endMarker[0].length);
    }
    // Unterminated PEM: fail closed and take the remainder rather than leak it.
    return spanTo(text, index, text.length);
  }

  // An UNQUOTED value runs to the end of the line, not to the next space.
  // Stopping at the space redacted only the first word of
  // `passphrase: correct horse battery staple` and left the rest -- and
  // `KEY: value` running to end-of-line is exactly the shape of the env dumps
  // and config echoes this channel actually carries. Over-redacting the tail of
  // a prose sentence is the cheaper error here; this is the diagnostic and
  // index channel, never the deliverable.
  const lineEnd = text.indexOf("\n", index);
  const end = lineEnd === -1 ? text.length : lineEnd;
  return end > index ? spanTo(text, index, end) : null;
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
    if (!found || isRedactedValue(text, found.value, separatorEnd + found.length)) {
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
