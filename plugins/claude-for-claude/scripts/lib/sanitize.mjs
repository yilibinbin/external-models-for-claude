import os from "node:os";
import path from "node:path";
import { canonicalWorkspaceRoot } from "./workspace.mjs";

const SECRET_PATTERNS = [
  /\bAKIA[0-9A-Z]{16}\b/g,
  /\bAIza[0-9A-Za-z_-]{35}\b/g,
  /\b(?:ghp|gho|ghu|ghs|ghr)_[0-9A-Za-z_]{20,}\b/g,
  /\bsk-[A-Za-z0-9_-]{20,}\b/g,
  // JSON / quoted key:value form, e.g. "password": "hunter2" or {"secret":'...'}
  /(["'`]?\b(?:api[_-]?key|token|secret|password|passwd|pwd)\b["'`]?\s*[:=]\s*)["'`][^"'`]+["'`]/gi,
  // bare (unquoted) key=value form. The negative lookahead only skips when the
  // value is EXACTLY the placeholder (followed by a delimiter or end), so this
  // stays idempotent without skipping a real value that merely starts with
  // "[secret]" (e.g. password=[secret]LEAKED would otherwise pass through).
  /\b(?:api[_-]?key|token|secret|password|passwd|pwd)\s*[:=]\s*(?!\[secret\](?:[\s"'`,}\]]|$))[^\s"'`,}]+/gi
];

const ANSI_PATTERN = /\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])/g;
const CONTROL_PATTERN = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g;

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function capUtf8(text, maxBytes, options = {}) {
  const limit = Number.isInteger(maxBytes) && maxBytes > 0 ? maxBytes : 2048;
  const forceTruncated = Boolean(options.forceTruncated);
  if (Buffer.byteLength(text, "utf8") <= limit && !forceTruncated) {
    return text;
  }
  const truncateFrom = options.truncateFrom === "head" ? "head" : "tail";
  const marker = truncateFrom === "head" ? "[truncated] " : " [truncated]";
  const markerBytes = Buffer.byteLength(marker, "utf8");
  if (markerBytes >= limit) {
    return marker.slice(0, limit);
  }
  if (truncateFrom === "head") {
    let output = "";
    const chars = [...text];
    for (let index = chars.length - 1; index >= 0; index -= 1) {
      const candidate = `${chars[index]}${output}`;
      if (Buffer.byteLength(candidate, "utf8") + markerBytes > limit) {
        break;
      }
      output = candidate;
    }
    return `${marker}${output}`;
  }
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
    // Patterns with a capture group keep the key prefix and redact only the value.
    output = output.replace(pattern, (match, keyPrefix) =>
      typeof keyPrefix === "string" ? `${keyPrefix}[secret]` : "[secret]"
    );
  }
  return output;
}

export function redactLocalPaths(text, { cwd = process.cwd(), env = process.env } = {}) {
  let output = String(text ?? "");
  const replacements = new Set();
  for (const candidate of [env.HOME, os.homedir(), canonicalWorkspaceRoot(cwd)]) {
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
  return capUtf8(redacted, options.maxBytes ?? 2048, options);
}

export function containsHighConfidenceSecret(text) {
  return SECRET_PATTERNS.some((pattern) => {
    pattern.lastIndex = 0;
    return pattern.test(String(text ?? ""));
  });
}
