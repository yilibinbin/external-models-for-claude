import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSyncWithRetry } from "./spawn-retry.mjs";

export const CLAUDE_CLI_PATH_ENV = "CLAUDE_CLI_PATH";

function spawnSync(command, args, options) {
  return spawnSyncWithRetry(command, args, options);
}

function isExecutable(filePath) {
  try {
    fs.accessSync(filePath, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

function findOnPath(commandName, env = process.env) {
  for (const entry of String(env.PATH || "").split(path.delimiter)) {
    if (!entry) continue;
    const candidate = path.join(entry, commandName);
    if (isExecutable(candidate)) return candidate;
  }
  return "";
}

function splitShebang(line) {
  const text = String(line || "").replace(/^#!/, "").trim();
  if (!text) return null;
  const parts = text.match(/(?:[^\s"']+|"[^"]*"|'[^']*')+/g)?.map((part) => part.replace(/^(['"])(.*)\1$/, "$2")) ?? [];
  return parts.length ? parts : null;
}

function normalizePosixScriptInvocation(command, args = []) {
  if (process.platform === "win32" || !path.isAbsolute(command)) {
    return { command, args };
  }
  let header = "";
  try {
    header = fs.readFileSync(command, { encoding: "utf8", flag: "r" }).split(/\r?\n/, 1)[0] || "";
  } catch {
    return { command, args };
  }
  if (!header.startsWith("#!")) {
    return { command, args };
  }
  const shebang = splitShebang(header);
  if (!shebang) {
    return { command, args };
  }
  const [interpreter, ...interpreterArgs] = shebang;
  return { command: interpreter, args: [...interpreterArgs, command, ...args] };
}

function expandExecutableCandidates(pattern) {
  const parts = path.resolve(pattern).split(path.sep);
  const results = [];

  function visit(index, current) {
    if (index >= parts.length) {
      results.push(current || path.sep);
      return;
    }
    const part = parts[index];
    if (!part) {
      visit(index + 1, path.sep);
      return;
    }
    if (part !== "*") {
      visit(index + 1, path.join(current || path.sep, part));
      return;
    }
    const dir = current || path.sep;
    let entries = [];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (entry.isDirectory()) {
        visit(index + 1, path.join(dir, entry.name));
      }
    }
  }

  visit(0, "");
  return results;
}

function candidateClaudeCommands(env = process.env) {
  const executableNames = process.platform === "win32" ? ["claude.cmd", "claude.exe", "claude"] : ["claude"];
  const home = env.HOME || os.homedir();
  const candidates = [];
  const add = (candidate) => {
    if (candidate) candidates.push(candidate);
  };
  const addBin = (dir) => {
    for (const name of executableNames) {
      add(dir ? path.join(dir, name) : "");
    }
  };

  addBin(path.join(home, ".local", "bin"));
  addBin(path.join(home, "bin"));
  addBin(path.join(home, ".npm-global", "bin"));
  addBin(path.join(home, ".volta", "bin"));
  addBin(path.join(home, ".asdf", "shims"));
  addBin(path.join(home, ".bun", "bin"));
  addBin(path.join(home, ".deno", "bin"));
  addBin(env.PNPM_HOME);
  addBin(env.NPM_CONFIG_PREFIX ? path.join(env.NPM_CONFIG_PREFIX, "bin") : "");
  addBin(env.npm_config_prefix ? path.join(env.npm_config_prefix, "bin") : "");
  addBin(env.HOMEBREW_PREFIX ? path.join(env.HOMEBREW_PREFIX, "bin") : "");

  for (const pattern of [
    path.join(home, ".nvm", "versions", "node", "*", "bin", "claude"),
    path.join(home, ".fnm", "node-versions", "*", "installation", "bin", "claude"),
    path.join(home, ".asdf", "installs", "nodejs", "*", "bin", "claude")
  ]) {
    candidates.push(...expandExecutableCandidates(pattern));
  }

  for (const dir of ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]) {
    addBin(dir);
  }
  return [...new Set(candidates)];
}

export function claudeCommand(env = process.env) {
  if (env[CLAUDE_CLI_PATH_ENV] && isExecutable(env[CLAUDE_CLI_PATH_ENV])) {
    return env[CLAUDE_CLI_PATH_ENV];
  }
  const pathCommand = findOnPath("claude", env);
  if (pathCommand) return pathCommand;
  for (const candidate of candidateClaudeCommands(env)) {
    if (isExecutable(candidate)) return candidate;
  }
  return "claude";
}

export function runClaude(args, options = {}) {
  const env = {
    ...(options.env || process.env),
    CLAUDE_FOR_CLAUDE_CHILD: "1"
  };
  const baseArgs = [
    "-p",
    "--safe-mode",
    "--no-session-persistence",
    "--tools",
    "",
    "--output-format",
    options.outputFormat || "text"
  ];
  if (options.model) {
    baseArgs.push("--model", options.model);
  }
  const invocation = normalizePosixScriptInvocation(claudeCommand(env), [...baseArgs, ...args]);
  const result = spawnSync(invocation.command, invocation.args, {
    cwd: options.cwd || process.cwd(),
    env,
    encoding: "utf8",
    input: options.input,
    maxBuffer: 20 * 1024 * 1024,
    timeout: options.timeout || 15 * 60 * 1000
  });
  return {
    status: result.status ?? 1,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
    error: result.error ? String(result.error.message || result.error) : "",
    errorCode: result.error?.code ? String(result.error.code) : ""
  };
}

export function parseClaudeJson(stdout) {
  let parsed;
  try {
    parsed = JSON.parse(stdout || "{}");
  } catch (error) {
    return { ok: false, response: "", error: `Invalid Claude JSON output: ${error.message}`, stats: {} };
  }
  if (parsed.error) {
    return { ok: false, response: "", error: JSON.stringify(parsed.error), stats: parsed.stats || {} };
  }
  if (parsed.is_error === true || (typeof parsed.subtype === "string" && parsed.subtype !== "success") || parsed.api_error_status) {
    const message = typeof parsed.result === "string" && parsed.result
      ? parsed.result
      : JSON.stringify(parsed.error || parsed.api_error_status || parsed);
    return { ok: false, response: "", error: message, stats: parsed.stats || {} };
  }
  const response = typeof parsed.response === "string"
    ? parsed.response
    : typeof parsed.result === "string"
      ? parsed.result
      : "";
  if (!response) {
    return { ok: false, response: "", error: "Claude JSON output did not include a string result.", stats: parsed.stats || {} };
  }
  return { ok: true, response, error: "", stats: parsed.stats || {} };
}
