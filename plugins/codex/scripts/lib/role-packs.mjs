export const FORBIDDEN_FIELDS = new Set(["tools", "command", "commands", "hooks", "env", "provider", "model", "max_effort", "shell"]);
export const MAX_PACK_BYTES = 64 * 1024;
export const MAX_NESTING_DEPTH = 8;
export const NAME_PATTERN = /^[a-z][a-z0-9-]{0,63}$/;

export const REVIEW_ROLES = {
  correctness: {
    id: "correctness",
    title: "Correctness",
    focus: "Find behavior bugs, broken assumptions, state errors, and edge-case regressions."
  },
  security: {
    id: "security",
    title: "Security",
    focus: "Find injection, auth, secret exposure, unsafe filesystem, and CI permission risks."
  },
  tests: {
    id: "tests",
    title: "Tests",
    focus: "Find missing regression tests, weak assertions, and test cases that would not fail for the bug."
  },
  release: {
    id: "release",
    title: "Release",
    focus: "Find install, versioning, docs, migration, compatibility, and rollback risks."
  },
  adversarial: {
    id: "adversarial",
    title: "Adversarial",
    focus: "Challenge the design and search for simpler or safer alternatives."
  }
};

export const ROLE_PACKS = {
  default: ["correctness", "security", "tests", "release", "adversarial"],
  security: ["security", "correctness", "tests"],
  release: ["release", "correctness", "tests"]
};

function assertSafeRole(role) {
  if (!role || typeof role !== "object") {
    throw new Error("Invalid role definition.");
  }
  for (const field of Object.keys(role)) {
    if (FORBIDDEN_FIELDS.has(field)) {
      throw new Error(`Forbidden role field: ${field}`);
    }
  }
  if (!NAME_PATTERN.test(String(role.id || ""))) {
    throw new Error(`Invalid review role id: ${role.id}`);
  }
}

export function resolveRoles({ roles = "", rolePack = "default" } = {}) {
  const ids = roles
    ? String(roles).split(",").map((item) => item.trim()).filter(Boolean)
    : ROLE_PACKS[rolePack];
  if (!ids) {
    throw new Error(`Unknown role pack: ${rolePack}`);
  }
  return ids.map((id) => {
    const role = REVIEW_ROLES[id];
    if (!role) {
      throw new Error(`Unknown review role: ${id}`);
    }
    assertSafeRole(role);
    return role;
  });
}
