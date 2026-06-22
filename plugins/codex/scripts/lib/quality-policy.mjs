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
    effort: "high",
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
