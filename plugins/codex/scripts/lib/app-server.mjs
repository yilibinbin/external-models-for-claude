/**
 * @typedef {Error & { data?: unknown, rpcCode?: number }} ProtocolError
 * @typedef {import("./app-server-protocol").AppServerMethod} AppServerMethod
 * @typedef {import("./app-server-protocol").AppServerNotification} AppServerNotification
 * @typedef {import("./app-server-protocol").AppServerNotificationHandler} AppServerNotificationHandler
 * @typedef {import("./app-server-protocol").ClientInfo} ClientInfo
 * @typedef {import("./app-server-protocol").CodexAppServerClientOptions} CodexAppServerClientOptions
 * @typedef {import("./app-server-protocol").InitializeCapabilities} InitializeCapabilities
 */
import fs from "node:fs";
import net from "node:net";
import process from "node:process";
import { spawn } from "node:child_process";
import readline from "node:readline";
import { parseBrokerEndpoint } from "./broker-endpoint.mjs";
import { ensureBrokerSession, loadBrokerSession } from "./broker-lifecycle.mjs";
import { terminateProcessTree } from "./process.mjs";

const PLUGIN_MANIFEST_URL = new URL("../../.claude-plugin/plugin.json", import.meta.url);
const PLUGIN_MANIFEST = JSON.parse(fs.readFileSync(PLUGIN_MANIFEST_URL, "utf8"));

export const BROKER_ENDPOINT_ENV = "CODEX_COMPANION_APP_SERVER_ENDPOINT";
// Transport-level notification the broker sends to every connected client when its
// backing app-server dies, so a streaming turn can report the real cause. Internal
// to the broker link; never emitted by codex itself.
export const BROKER_APP_SERVER_EXIT_METHOD = "broker/appServerExited";

export const BROKER_BUSY_RPC_CODE = -32001;
// The handshake should be near-instant; bound it so a wedged app-server that
// never emits the initialize response fails fast instead of hanging forever.
const INITIALIZE_TIMEOUT_MS = 30 * 1000;

/** @type {ClientInfo} */
const DEFAULT_CLIENT_INFO = {
  title: "Codex Plugin",
  name: "Claude Code",
  version: PLUGIN_MANIFEST.version ?? "0.0.0"
};

/** @type {InitializeCapabilities} */
const DEFAULT_CAPABILITIES = {
  experimentalApi: false,
  optOutNotificationMethods: [
    "item/agentMessage/delta",
    "item/reasoning/summaryTextDelta",
    "item/reasoning/summaryPartAdded",
    "item/reasoning/textDelta"
  ]
};

// Render a structured exit reason into text. The inputs are validated to a tiny
// alphabet on the receiving side, so this can never become a channel for child bytes.
const PROTOCOL_EXIT_REASONS = new Set(["malformed-output"]);

function describeExit(reason) {
  if (reason?.protocol && PROTOCOL_EXIT_REASONS.has(reason.protocol)) {
    return `protocol error: ${reason.protocol}`;
  }
  if (reason?.signal) {
    return `signal ${reason.signal}`;
  }
  if (Number.isInteger(reason?.code)) {
    return `exit ${reason.code}`;
  }
  return "reason unknown";
}

function buildJsonRpcError(code, message, data) {
  return data === undefined ? { code, message } : { code, message, data };
}

function createProtocolError(message, data) {
  const error = /** @type {ProtocolError} */ (new Error(message));
  error.data = data;
  if (data?.code !== undefined) {
    error.rpcCode = data.code;
  }
  return error;
}

class AppServerClientBase {
  constructor(cwd, options = {}) {
    this.cwd = cwd;
    this.options = options;
    this.pending = new Map();
    this.nextId = 1;
    this.stderr = "";
    this.closed = false;
    this.exitError = null;
    /** @type {AppServerNotificationHandler | null} */
    this.notificationHandler = null;
    this.lineBuffer = "";
    this.transport = "unknown";

    this.exitPromise = new Promise((resolve) => {
      this.resolveExit = resolve;
    });
  }

  setNotificationHandler(handler) {
    this.notificationHandler = handler;
  }

  /**
   * @template {AppServerMethod} M
   * @param {M} method
   * @param {import("./app-server-protocol").AppServerRequestParams<M>} params
   * @returns {Promise<import("./app-server-protocol").AppServerResponse<M>>}
   */
  request(method, params) {
    if (this.closed) {
      throw new Error("codex app-server client is closed.");
    }

    const id = this.nextId;
    this.nextId += 1;

    // Most RPCs (review/start, turn/start) are intentionally long-running and
    // must not be bounded here. Only handshake RPCs opt into a timeout via
    // `timeoutMs` so a wedged app-server cannot hang connect()/initialize().
    const timeoutMs = Number.isInteger(this.requestTimeoutOverrideMs) && this.requestTimeoutOverrideMs > 0
      ? this.requestTimeoutOverrideMs
      : 0;

    return new Promise((resolve, reject) => {
      let timer = null;
      if (timeoutMs > 0) {
        timer = setTimeout(() => {
          const pending = this.pending.get(id);
          if (!pending) {
            return;
          }
          this.pending.delete(id);
          pending.reject(createProtocolError(`codex app-server did not respond to "${method}" within ${timeoutMs}ms.`));
        }, timeoutMs);
        if (typeof timer.unref === "function") {
          timer.unref();
        }
      }
      this.pending.set(id, { resolve, reject, method, timer });
      this.sendMessage({ id, method, params });
    });
  }

  async requestWithTimeout(method, params, timeoutMs) {
    this.requestTimeoutOverrideMs = timeoutMs;
    try {
      return await this.request(method, params);
    } finally {
      this.requestTimeoutOverrideMs = 0;
    }
  }

  notify(method, params = {}) {
    if (this.closed) {
      return;
    }
    this.sendMessage({ method, params });
  }

  handleChunk(chunk) {
    this.lineBuffer += chunk;
    let newlineIndex = this.lineBuffer.indexOf("\n");
    while (newlineIndex !== -1) {
      const line = this.lineBuffer.slice(0, newlineIndex);
      this.lineBuffer = this.lineBuffer.slice(newlineIndex + 1);
      this.handleLine(line);
      newlineIndex = this.lineBuffer.indexOf("\n");
    }
  }

  handleLine(line) {
    if (!line.trim()) {
      return;
    }

    let message;
    try {
      message = JSON.parse(line);
    } catch (error) {
      // A protocol death resolves exitPromise right here, BEFORE the child's 'exit'
      // event fires, so the reason must be recorded now or the broker's handler finds
      // none and the cause is lost. It is an enum, not text: the parse Error quotes the
      // offending child bytes, so that message must never be what travels.
      this.exitReason = { protocol: "malformed-output" };
      this.handleExit(createProtocolError(`Failed to parse codex app-server JSONL: ${error.message}`, { line }));
      return;
    }

    if (message.id !== undefined && message.method) {
      this.handleServerRequest(message);
      return;
    }

    if (message.id !== undefined) {
      const pending = this.pending.get(message.id);
      if (!pending) {
        return;
      }
      this.pending.delete(message.id);
      if (pending.timer) {
        clearTimeout(pending.timer);
      }

      if (message.error) {
        pending.reject(createProtocolError(message.error.message ?? `codex app-server ${pending.method} failed.`, message.error));
      } else {
        pending.resolve(message.result ?? {});
      }
      return;
    }

    // Broker-internal: the backing app-server died. Record it as this connection's
    // exit cause BEFORE the socket closes, so a streaming turn — which has no pending
    // request left to reject — still surfaces the real reason instead of the generic
    // "connection closed". Not forwarded to the notification handler: it is a
    // transport event, not an app-server notification.
    if (message.method === BROKER_APP_SERVER_EXIT_METHOD) {
      if (!this.exitResolved && !this.exitError) {
        // Only a validated code/signal is accepted, and the text is built from a local
        // template. Any free-text field on this notification is IGNORED: the broker's
        // own exitError can embed child stdout (a JSON parse failure quotes the
        // offending bytes), so relaying its message would reopen the channel this
        // design exists to close.
        const { code, signal } = message.params ?? {};
        const reason = {};
        const { protocol } = message.params ?? {};
        if (typeof protocol === "string" && PROTOCOL_EXIT_REASONS.has(protocol)) {
          reason.protocol = protocol;
        } else if (typeof signal === "string" && /^[A-Z][A-Z0-9]*$/.test(signal)) {
          reason.signal = signal;
        } else if (Number.isInteger(code)) {
          reason.code = code;
        }
        this.exitError = createProtocolError(
          `codex app-server exited unexpectedly (${describeExit(reason)}).`
        );
      }
      return;
    }

    if (message.method && this.notificationHandler) {
      this.notificationHandler(/** @type {AppServerNotification} */ (message));
    }
  }

  handleServerRequest(message) {
    this.sendMessage({
      id: message.id,
      error: buildJsonRpcError(-32601, `Unsupported server request: ${message.method}`)
    });
  }

  handleExit(error) {
    if (this.exitResolved) {
      return;
    }

    this.exitResolved = true;
    this.exitError = error ?? null;

    for (const pending of this.pending.values()) {
      if (pending.timer) {
        clearTimeout(pending.timer);
      }
      pending.reject(this.exitError ?? new Error("codex app-server connection closed."));
    }
    this.pending.clear();
    this.resolveExit(undefined);
  }

  sendMessage(_message) {
    throw new Error("sendMessage must be implemented by subclasses.");
  }
}

class SpawnedCodexAppServerClient extends AppServerClientBase {
  constructor(cwd, options = {}) {
    super(cwd, options);
    this.transport = "direct";
  }

  async initialize() {
    this.proc = spawn("codex", ["app-server"], {
      cwd: this.cwd,
      env: this.options.env ?? process.env,
      stdio: ["pipe", "pipe", "pipe"],
      shell: process.platform === "win32" ? (process.env.SHELL || true) : false,
      windowsHide: true
    });

    this.proc.stdout.setEncoding("utf8");
    this.proc.stderr.setEncoding("utf8");

    this.proc.stderr.on("data", (chunk) => {
      this.stderr += chunk;
    });

    this.proc.on("error", (error) => {
      this.handleExit(error);
    });

    this.proc.on("exit", (code, signal) => {
      // Record the exit reason as STRUCTURED data. It is deliberately not built from
      // child output: quoting the child's stderr here was tried and withdrawn, because
      // its content is unbounded and un-authored by this plugin, so no redaction pass
      // can bound what it might contain. Only the exit code / signal name travels.
      this.exitReason = signal ? { signal } : { code };
      this.handleExit(
        code === 0 ? null : createProtocolError(`codex app-server exited unexpectedly (${describeExit(this.exitReason)}).`)
      );
    });

    this.readline = readline.createInterface({ input: this.proc.stdout });
    this.readline.on("line", (line) => {
      this.handleLine(line);
    });

    await this.requestWithTimeout("initialize", {
      clientInfo: this.options.clientInfo ?? DEFAULT_CLIENT_INFO,
      capabilities: this.options.capabilities ?? DEFAULT_CAPABILITIES
    }, INITIALIZE_TIMEOUT_MS);
    this.notify("initialized", {});
  }

  async close() {
    if (this.closed) {
      await this.exitPromise;
      return;
    }

    this.closed = true;

    if (this.readline) {
      this.readline.close();
    }

    // Release the child's stdio unconditionally. These pipes stay open for as long as
    // ANY descendant holds the inherited descriptor, and an open pipe pins this
    // process's event loop: measured on the bare topology, a parent listening on
    // stderr exits in 60ms normally and never exits once a grandchild inherits it
    // (killed at the 10s timeout). This predates the crash-diagnostic work — main has
    // the same accumulator with no release — and it must run on the clean-exit path
    // too, which an exit-handler-only fix would miss.
    this.proc?.stdout?.destroy();
    this.proc?.stderr?.destroy();

    if (this.proc && !this.proc.killed) {
      this.proc.stdin.end();
      setTimeout(() => {
        if (this.proc && !this.proc.killed && this.proc.exitCode === null) {
          // On Windows with shell: true, the direct child is cmd.exe.
          // Use terminateProcessTree to kill the entire tree including
          // the grandchild node process.
          if (process.platform === "win32") {
            try {
              terminateProcessTree(this.proc.pid);
            } catch {
              // Best-effort cleanup inside an unref'd timer — swallow errors
              // to avoid crashing the host process during shutdown.
            }
          } else {
            this.proc.kill("SIGTERM");
          }
        }
      }, 50).unref?.();
    }

    // Bound the wait: a wedged child that ignores SIGTERM must not hang close()
    // forever (that would defeat the initialize timeout). Escalate to SIGKILL /
    // terminateProcessTree and resolve regardless after a short grace period.
    await this.awaitExitWithDeadline(() => {
      if (this.proc && !this.proc.killed && this.proc.exitCode === null) {
        try {
          terminateProcessTree(this.proc.pid);
        } catch {
          // Best-effort; fall through to the hard-kill below.
        }
        // terminateProcessTree only delivers SIGTERM on POSIX, so a child that
        // ignores SIGTERM would otherwise survive. Always escalate to SIGKILL
        // if it has not exited.
        if (this.proc.exitCode === null) {
          try { this.proc.kill("SIGKILL"); } catch { /* already gone */ }
        }
      }
    });
  }

  async awaitExitWithDeadline(onTimeout, graceMs = 2000) {
    let timer = null;
    const guard = new Promise((resolve) => {
      timer = setTimeout(() => {
        try { onTimeout?.(); } catch { /* best-effort */ }
        // Settle exitPromise so the `if (this.closed) await this.exitPromise`
        // fast-path in close() can never block on a genuinely unkillable child
        // (whose proc 'exit'/socket 'close' never fires) after the guard fired.
        try { this.resolveExit(undefined); } catch { /* already settled */ }
        resolve();
      }, graceMs);
      timer.unref?.();
    });
    try {
      await Promise.race([this.exitPromise, guard]);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  sendMessage(message) {
    const line = `${JSON.stringify(message)}\n`;
    const stdin = this.proc?.stdin;
    if (!stdin) {
      throw new Error("codex app-server stdin is not available.");
    }
    stdin.write(line);
  }
}

class BrokerCodexAppServerClient extends AppServerClientBase {
  constructor(cwd, options = {}) {
    super(cwd, options);
    this.transport = "broker";
    this.endpoint = options.brokerEndpoint;
  }

  async initialize() {
    await new Promise((resolve, reject) => {
      const target = parseBrokerEndpoint(this.endpoint);
      this.socket = net.createConnection({ path: target.path });
      this.socket.setEncoding("utf8");
      this.socket.on("connect", resolve);
      this.socket.on("data", (chunk) => {
        this.handleChunk(chunk);
      });
      this.socket.on("error", (error) => {
        if (!this.exitResolved) {
          reject(error);
        }
        this.handleExit(error);
      });
      this.socket.on("close", () => {
        this.handleExit(this.exitError);
      });
    });

    await this.requestWithTimeout("initialize", {
      clientInfo: this.options.clientInfo ?? DEFAULT_CLIENT_INFO,
      capabilities: this.options.capabilities ?? DEFAULT_CAPABILITIES
    }, INITIALIZE_TIMEOUT_MS);
    this.notify("initialized", {});
  }

  async close() {
    if (this.closed) {
      await this.exitPromise;
      return;
    }

    this.closed = true;
    if (this.socket) {
      this.socket.end();
    }
    // Bound the wait so a half-open/unresponsive broker socket cannot hang
    // close() forever and defeat the initialize timeout. Force-destroy and
    // resolve after a short grace period.
    let timer = null;
    const guard = new Promise((resolve) => {
      timer = setTimeout(() => {
        try { this.socket?.destroy(); } catch { /* already gone */ }
        resolve();
      }, 2000);
      timer.unref?.();
    });
    try {
      await Promise.race([this.exitPromise, guard]);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  sendMessage(message) {
    const line = `${JSON.stringify(message)}\n`;
    const socket = this.socket;
    if (!socket) {
      throw new Error("codex app-server broker connection is not connected.");
    }
    socket.write(line);
  }
}

export class CodexAppServerClient {
  static async connect(cwd, options = {}) {
    let brokerEndpoint = null;
    if (!options.disableBroker) {
      brokerEndpoint = options.brokerEndpoint ?? options.env?.[BROKER_ENDPOINT_ENV] ?? process.env[BROKER_ENDPOINT_ENV] ?? null;
      if (!brokerEndpoint && options.reuseExistingBroker) {
        brokerEndpoint = loadBrokerSession(cwd)?.endpoint ?? null;
      }
      if (!brokerEndpoint && !options.reuseExistingBroker) {
        const brokerSession = await ensureBrokerSession(cwd, { env: options.env });
        brokerEndpoint = brokerSession?.endpoint ?? null;
      }
    }
    const client = brokerEndpoint
      ? new BrokerCodexAppServerClient(cwd, { ...options, brokerEndpoint })
      : new SpawnedCodexAppServerClient(cwd, options);
    try {
      await client.initialize();
    } catch (error) {
      // initialize() can reject on INITIALIZE_TIMEOUT_MS against a wedged
      // app-server. connect() throws before returning, so the caller's
      // `if (client) await client.close()` cleanup never runs — tear down the
      // half-built client here to avoid orphaning the spawned child / socket.
      await client.close().catch(() => {});
      throw error;
    }
    return client;
  }
}
