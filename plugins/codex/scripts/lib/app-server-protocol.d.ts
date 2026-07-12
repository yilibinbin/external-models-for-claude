import type {
  ClientInfo,
  InitializeCapabilities,
  InitializeParams,
  InitializeResponse,
  ServerNotification
} from "../../.generated/app-server-types/index.js";
import type {
  ReviewStartParams,
  ReviewStartResponse,
  ReviewTarget,
  Thread,
  ThreadItem,
  ThreadListParams,
  ThreadListResponse,
  ThreadResumeParams as RawThreadResumeParams,
  ThreadResumeResponse,
  ThreadSetNameParams,
  ThreadSetNameResponse,
  ThreadStartParams as RawThreadStartParams,
  ThreadStartResponse,
  Turn,
  TurnInterruptParams,
  TurnInterruptResponse,
  TurnStartParams,
  TurnStartResponse,
  UserInput
} from "../../.generated/app-server-types/v2/index.js";

export type {
  ClientInfo,
  InitializeCapabilities,
  InitializeParams,
  InitializeResponse,
  ReviewTarget,
  Thread,
  ThreadItem,
  ThreadListParams,
  Turn,
  TurnInterruptParams,
  TurnStartParams,
  UserInput
};

export type ThreadStartParams = Omit<RawThreadStartParams, "persistExtendedHistory">;
export type ThreadResumeParams = Omit<RawThreadResumeParams, "persistExtendedHistory">;

// `model/list` is not exported by the generated app-server types, so its contract is declared
// locally here. Field names mirror the REAL app-server response probed at implementation time
// (spec v6 §9): model key `id`; per-model `supportedReasoningEfforts` with `{reasoningEffort}`
// elements; `defaultReasoningEffort`; `isDefault`. The effort resolver (effort-policy.mjs) reads
// exactly these fields, so this is the authoritative capability contract it depends on.
export interface ModelReasoningEffort {
  reasoningEffort: string;
  description?: string;
}
export interface ModelListEntry {
  id: string;
  model?: string;
  isDefault?: boolean;
  supportedReasoningEfforts: ModelReasoningEffort[];
  defaultReasoningEffort?: string;
}
export interface ModelListParams {
  // Pagination (codex MCP interface): opaque `cursor` from a prior response's `nextCursor`,
  // optional server-side `limit`. Omit both to fetch the first page with the server default size.
  cursor?: string;
  limit?: number;
}
export interface ModelListResponse {
  data: ModelListEntry[];
  nextCursor?: string | null;
}

export interface CodexAppServerClientOptions {
  env?: NodeJS.ProcessEnv;
  clientInfo?: ClientInfo;
  capabilities?: InitializeCapabilities;
  brokerEndpoint?: string;
  disableBroker?: boolean;
  reuseExistingBroker?: boolean;
}

export interface AppServerMethodMap {
  initialize: { params: InitializeParams; result: InitializeResponse };
  "thread/start": { params: ThreadStartParams; result: ThreadStartResponse };
  "thread/resume": { params: ThreadResumeParams; result: ThreadResumeResponse };
  "thread/name/set": { params: ThreadSetNameParams; result: ThreadSetNameResponse };
  "thread/list": { params: ThreadListParams; result: ThreadListResponse };
  "model/list": { params: ModelListParams; result: ModelListResponse };
  "review/start": { params: ReviewStartParams; result: ReviewStartResponse };
  "turn/start": { params: TurnStartParams; result: TurnStartResponse };
  "turn/interrupt": { params: TurnInterruptParams; result: TurnInterruptResponse };
}

export type AppServerMethod = keyof AppServerMethodMap;
export type AppServerRequestParams<M extends AppServerMethod> = AppServerMethodMap[M]["params"];
export type AppServerResponse<M extends AppServerMethod> = AppServerMethodMap[M]["result"];
export type AppServerNotification = ServerNotification;
export type AppServerNotificationHandler = (message: AppServerNotification) => void;
