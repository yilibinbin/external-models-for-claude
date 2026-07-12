const POLICIES = {
  fast: {
    quality: "fast",
    effort: "low",
    nativeReviewEffect: "metadata-only",
    explanation: "Fast Codex turn for small changes."
  },
  standard: {
    quality: "standard",
    effort: "medium",
    nativeReviewEffect: "metadata-only",
    explanation: "Default balanced Codex turn."
  },
  strong: {
    quality: "strong",
    effort: "high",
    nativeReviewEffect: "metadata-only",
    explanation: "Higher-effort Codex turn."
  },
  max: {
    quality: "max",
    // effort is resolved per-model at session time (highest tier the current model supports).
    // Kept null here so the sentinel object never reaches normalizeReasoningEffort/turn/start;
    // the highest-tier intent travels via the wantsHighestEffort boolean instead.
    effort: null,
    wantsHighestEffort: true,
    nativeReviewEffect: "metadata-only",
    explanation: "Maximum-effort Codex turn for release-critical work."
  }
};

export function resolveQuality(value = "standard") {
  const key = String(value || "standard").toLowerCase();
  const policy = POLICIES[key];
  if (!policy) {
    throw new Error("--quality must be fast, standard, strong, or max.");
  }
  return policy;
}
