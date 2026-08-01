# Version Axis Confirmation

Schema/docs source checked:

- Claude Code CLI version output checked with `claude --version`: `2.1.181 (Claude Code)`
- CLI command resolution checked with `command -v claude`; no home-directory path is recorded in this evidence file.
- CLI schema help checked with `claude plugin validate --strict --help`
- No separate installed schema or marketplace documentation files were found in the active Claude Code installation during local inspection.
- Per-entry marketplace `version` support is confirmed by paired strict-validation probe: a valid string value passed and an invalid object value failed.

Baseline commands:

- `claude plugin validate --strict .claude-plugin/marketplace.json` exited 0.
- `claude plugin validate --strict plugins/codex` exited 0.
- `claude plugin list --json` live schema probe exited 0. The local `codex@external-models-for-claude` marketplace plugin was not installed, so installed Codex root compatibility is explicitly unverified/skipped and no root field was verified.

Throwaway version-axis commands:

- `claude plugin validate --strict "$tmp_repo/repo/.claude-plugin/marketplace.json"` with marketplace `metadata.version = "0.2.0"` and codex entry `version = "1.1.0-fh.4"` exited 0.
- `claude plugin validate --strict "$tmp_repo/repo/plugins/codex"` with codex manifest `version = "1.1.0-fh.4"` exited 0.
- `claude plugin validate --strict "$tmp_repo/repo/.claude-plugin/marketplace.json"` after setting codex entry `version = { "invalid": true }` exited 1 with `plugins.0.version: Invalid input: expected string, received object`.

The three "Accepted ..." values immediately below record the version axis **as probed at the
time of the original run**; they are historical evidence, not a statement of what ships today.
The current shipping values are listed under "Current version axis" at the end of this file and
are what `release-check` compares against.

Accepted marketplace metadata version (original probe): `0.2.0`

Accepted codex marketplace entry version (original probe): `1.1.0-fh.4`

Accepted codex plugin manifest version (original probe): `1.1.0-fh.4`

Negative invalid-entry-version probe result: rejected by strict validation with exit code 1.

marketplaceEntryVersionSupported: true

validatorUnavailable: false

Fallback decision (original probe): no fallback needed. Use marketplace tag/version `v0.2.0` / `0.2.0` and Codex local extension version `1.1.0-fh.4`.

fh.4 re-validation (2026-07-12): `claude plugin validate --strict .claude-plugin/marketplace.json` and `claude plugin validate --strict plugins/codex` were re-run against the bumped `1.1.0-fh.4` manifests and both exited 0 ("Validation passed"). The version-axis assertions above are verified for fh.4, not inherited from the fh.3 run.

fh.5 re-validation (2026-07-22): `claude plugin validate --strict .claude-plugin/marketplace.json` and `claude plugin validate --strict plugins/codex` were re-run against the bumped `1.1.0-fh.5` manifests and both exited 0 ("Validation passed"). What this re-run verifies for fh.5 — rather than inheriting from fh.4 — is the axis itself: `marketplaceEntryVersionSupported: true` and `validatorUnavailable: false` still hold, and the values now shipping are the ones under "Current version axis" below. The `(original probe)` lines above remain historical and are not re-asserted here.

fh.7 re-validation (2026-07-31): `claude plugin validate --strict .claude-plugin/marketplace.json` and `claude plugin validate --strict plugins/codex` were re-run against the bumped `1.1.0-fh.7` manifests and both exited 0 ("Validation passed"), as did `plugins/review-chain` at `0.1.2`. The axis flags (`marketplaceEntryVersionSupported: true`, `validatorUnavailable: false`) still hold; the shipping values are the ones under "Current version axis" below.

fh.8 re-validation (2026-08-01): `claude plugin validate --strict .claude-plugin/marketplace.json`, `claude plugin validate --strict plugins/codex` and `claude plugin validate --strict plugins/review-chain` were re-run against the bumped `1.1.0-fh.8` manifests and all three exited 0 ("Validation passed"). The bump is forced rather than cosmetic: `1.1.0-fh.7` shipped with the output-redaction work, so the app-server crash diagnostics cannot reuse that key without giving one version two byte trees. The axis flags (`marketplaceEntryVersionSupported: true`, `validatorUnavailable: false`) still hold.

fh.9 re-validation (2026-08-01): `claude plugin validate --strict .claude-plugin/marketplace.json`, `claude plugin validate --strict plugins/codex` and `claude plugin validate --strict plugins/review-chain` were re-run against the bumped `1.1.0-fh.9` manifests and all three exited 0 ("Validation passed"). This bump carries no code change: it exists because fh.7 and fh.8 each landed as multi-commit merges whose intermediate commits published differing trees under one version key. The axis flags (`marketplaceEntryVersionSupported: true`, `validatorUnavailable: false`) still hold.

## Current version axis

These are the values that ship today, each verified by the fh.9 re-validation above.

- Marketplace metadata version: `0.5.0`
- Codex marketplace entry version: `1.1.0-fh.9`
- Codex plugin manifest version: `1.1.0-fh.9`

The marketplace metadata version is no longer pinned inside this plugin (see the `1.1.0-fh.5`
changelog entry): pinning it here made every marketplace bump edit codex's shipped bytes under
an unchanged `CODEX_VERSION`. It is asserted in `tests/`, which ships in no plugin.
