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

Throwaway version-axis commands:

- `claude plugin validate --strict "$tmp_repo/repo/.claude-plugin/marketplace.json"` with marketplace `metadata.version = "0.2.0"` and codex entry `version = "1.1.0-fh.1"` exited 0.
- `claude plugin validate --strict "$tmp_repo/repo/plugins/codex"` with codex manifest `version = "1.1.0-fh.1"` exited 0.
- `claude plugin validate --strict "$tmp_repo/repo/.claude-plugin/marketplace.json"` after setting codex entry `version = { "invalid": true }` exited 1 with `plugins.0.version: Invalid input: expected string, received object`.

Accepted marketplace metadata version: `0.2.0`

Accepted codex marketplace entry version: `1.1.0-fh.1`

Accepted codex plugin manifest version: `1.1.0-fh.1`

Negative invalid-entry-version probe result: rejected by strict validation with exit code 1.

marketplaceEntryVersionSupported: true

validatorUnavailable: false

Fallback decision: no fallback needed. Use marketplace tag/version `v0.2.0` / `0.2.0` and Codex local extension version `1.1.0-fh.1`.
