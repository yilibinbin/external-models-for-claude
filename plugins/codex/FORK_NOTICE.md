# Fork Notice

This repository contains OpenAI-authored Apache-2.0 Codex Claude Code plugin files under `plugins/codex`, with local marketplace extensions maintained here.

- Plugin name: `codex`
- Local extended version: `1.1.0-fh.1`
- Bundled license: Apache License, Version 2.0
- Lineage note: this notice preserves bundled OpenAI attribution and documents local extension work. This notice does not use remote repository reachability as byte-level fork attestation or assert an upstream release version; any unverified upstream lineage is intentionally described as unverified.
- Changelog note: document only the local `1.1.0-fh.1` extension work; do not invent historical notes for earlier bundled versions.

This repository preserves OpenAI's `LICENSE` and `NOTICE` files under `plugins/codex`.

Local extensions are maintained by fanghao for the `external-models-for-claude` marketplace. This notice records the release baseline for the maturity work and is not a byte-for-byte upstream attestation. These extensions keep Codex as the only provider for this plugin and do not add Gemini, Antigravity, or Claude model-provider routing.

The global resource governor core at `scripts/lib/resource-governor-core.mjs` is ported from fanghao's Gemini/Antigravity governor work covered by this repository's root MIT license, with Codex-specific additions for the Codex-hosted plugin wrapper, task worker lease transfer, and terminal job cleanup.

Daemonless v1 limitation: stale background-job lease reclamation uses pid liveness and persisted job-state evidence without a supervising daemon, so very fast pid reuse can temporarily make an old lease look alive until terminal job cleanup or stale/dead-pid reaping corrects it.
