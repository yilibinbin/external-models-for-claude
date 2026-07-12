// Per-model reasoning-effort routing driven by the app-server `model/list` capability table.
// Field names below are confirmed against the REAL app-server model/list response (spec v6 §9 probe):
//   model key `id`; per-model `supportedReasoningEfforts` with elements `{reasoningEffort, description}`;
//   `defaultReasoningEffort`; `isDefault` bool. (NOT models_cache.json's `slug`/`effort` shape.)

// Known effort strength ordering (used only to pick the strongest KNOWN tier; not a legality source).
// Maintenance point: append here when codex ships a new tier; tiers not listed trigger fail-loud
// in highestKnownEffort. none/minimal are retained for ordering completeness only — no model lists
// them in supportedReasoningEfforts, so they can never be selected as the highest tier.
const EFFORT_ORDER = ["none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"];

// Union of all effort names this plugin knows about — used by the CLI-layer syntax pre-check
// (reject obviously-bad values like "hyper" at parse) BEFORE per-model legality is checked
// against a live model/list inside the session.
export const KNOWN_EFFORTS = new Set(EFFORT_ORDER);

// Extract a model entry's supported effort names (pure data transform, no I/O).
export function supportedEffortsOf(modelEntry) {
  return (modelEntry?.supportedReasoningEfforts || []).map((lv) => lv.reasoningEffort);
}

// Select the "current model" entry from model/list: explicit model id wins, else the isDefault model.
export function resolveModelEntry(models, requestedModel) {
  if (requestedModel) {
    return models.find((m) => (m.id || m.model) === requestedModel) || null; // miss -> null (caller decides)
  }
  return models.find((m) => m.isDefault) || null;
}

// The model's strongest tier: highest by EFFORT_ORDER within its supported set.
// Empty/non-array supported -> fail-loud (never silently degrade to default).
// A supported tier outside EFFORT_ORDER -> fail-loud (never guess the strongest).
export function highestKnownEffort(supported) {
  if (!Array.isArray(supported) || supported.length === 0) {
    throw new Error("Codex returned an empty reasoning-effort capability list; refusing to guess the strongest tier.");
  }
  const unknown = supported.filter((e) => !EFFORT_ORDER.includes(e));
  if (unknown.length) {
    throw new Error(
      `Codex reported unknown reasoning effort(s) [${unknown.join(", ")}] not in this plugin's known set ` +
      `[${EFFORT_ORDER.join(", ")}]; update effort-policy.mjs. Refusing to guess the strongest tier.`
    );
  }
  return supported.reduce((best, e) =>
    EFFORT_ORDER.indexOf(e) > EFFORT_ORDER.indexOf(best) ? e : best, supported[0]);
}

// The single session-time effort resolver (spec v6 §3.3/§3.4). Called inside runAppServerTurn's
// withAppServer callback, the only layer holding the app-server client. Pure given its inputs:
//   models             — the model/list `data` array, or null when model/list FAILED
//   requestedModel     — canonical model id (or null for the default model)
//   effort             — the user's explicit --effort (syntax-pre-checked scalar) or null; for a
//                        non-max preset this carries the preset's default tier (low/medium/high)
//   wantsHighestEffort — true only for --quality max
// Returns { effort: <string|null>, warning: <string|null> }; throws (fail-loud) for unknown model,
// unsupported explicit effort, empty capability list, or no-default-model under a max request.
export function resolveTurnEffort({ models, requestedModel, effort, wantsHighestEffort }) {
  // §3.4 model/list FAILURE: omit effort for ALL models + warn. Never validate (supported unknown),
  // never guess a tier — omitting is always legal and lets the app-server use its default.
  if (models == null) {
    return {
      effort: null,
      warning: "Could not confirm model reasoning-effort capability (model/list unavailable); " +
               "running at the app-server default tier (degraded).",
    };
  }

  const entry = resolveModelEntry(models, requestedModel);

  // §3.4: explicit unknown model -> fail loud (do not silently proceed).
  if (requestedModel && !entry) {
    throw new Error(`Unknown model "${requestedModel}": cannot verify its reasoning-effort capability.`);
  }

  // §3.4/§5: model=null and no isDefault entry. No model was resolved, so there is no capability
  // list to validate against. wantsHighestEffort -> fail loud (can't define "strongest"). Otherwise
  // OMIT effort (never forward an unverified tier, per spec line 145) — a forwarded effort could be
  // illegal for whatever model the app-server ends up choosing, causing a late turn/start failure
  // and breaking the per-model verification guarantee. If the user gave an explicit effort, surface
  // a warning so the silent drop is visible (fail-loud); a null effort is omitted silently.
  if (!entry) {
    if (wantsHighestEffort) {
      throw new Error("No default model reported by codex; cannot resolve the strongest reasoning effort for --quality max.");
    }
    return {
      effort: null,
      warning: effort != null
        ? "Could not confirm the model reasoning-effort capability (codex reported no default model); " +
          `ignoring the requested effort "${effort}" and running at the app-server default tier (degraded).`
        : null,
    };
  }

  const supported = supportedEffortsOf(entry);

  // §3.3 resolution order. Explicit effort wins over the highest-tier sentinel: for --quality max
  // the preset sets effort=null, so a non-null `effort` here can only be the user's explicit --effort.
  if (effort != null) {
    return { effort: validateEffortForModel(effort, supported), warning: null };
  }
  if (wantsHighestEffort) {
    return { effort: highestKnownEffort(supported), warning: null };
  }
  return { effort: null, warning: null };
}

// Validate a user-supplied effort against a specific model's real capability (the "verification step").
// Only ever called when `supported` is available; on model/list failure the caller omits effort instead.
export function validateEffortForModel(value, supported) {
  if (value == null) return null;
  const normalized = String(value).trim().toLowerCase();
  if (!normalized) return null;
  if (!Array.isArray(supported)) {
    throw new Error("validateEffortForModel called without a capability list; caller must guard on model/list failure.");
  }
  if (!supported.includes(normalized)) {
    throw new Error(
      `Model does not support reasoning effort "${value}". Supported: ${supported.join(", ")}.`
    );
  }
  return normalized;
}
