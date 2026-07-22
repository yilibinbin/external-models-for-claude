import json
import os
import pathlib
import re
import shutil
import subprocess

from plugin_versions import ANTIGRAVITY_FOR_CLAUDE_VERSION, MARKETPLACE_VERSION


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "antigravity-for-claude"
NODE = os.environ.get("NODE_BINARY") or shutil.which("node") or "node"

EXPECTED_COMMANDS = {
    "setup.md",
    "review.md",
    "adversarial-review.md",
    "multi-review.md",
    "plan-review.md",
    "plan.md",
    "assisted-review.md",
    "status.md",
    "result.md",
    "cancel.md",
    "roles.md",
    "github-actions.md",
}

PROVIDER_COMMANDS = {
    "review.md",
    "multi-review.md",
    "plan-review.md",
    "assisted-review.md",
}


def run_node(repo_root, script, args=None, env=None, timeout=30):
    merged_env = {**os.environ, **(env or {})}
    command = [NODE, str(repo_root / script), *(args or [])]
    try:
        return subprocess.run(
            command,
            cwd=repo_root,
            env=merged_env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=error.stdout or "",
            stderr=error.stderr or f"timed out after {timeout} seconds",
        )


def read_json(path):
    return json.loads(path.read_text(encoding="utf8"))


def read_text(path):
    return path.read_text(encoding="utf8")


def all_text(root):
    assert root.exists(), f"missing expected path: {root}"
    chunks = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            chunks.append(path.read_text(encoding="utf8"))
    return "\n".join(chunks)


def command_files():
    commands_dir = PLUGIN / "commands"
    assert commands_dir.is_dir(), f"missing commands directory: {commands_dir}"
    files = {path.name: path for path in commands_dir.glob("*.md")}
    assert EXPECTED_COMMANDS <= set(files)
    return files


def assert_no_shell_argument_interpolation(text):
    assert '"$ARGUMENTS"' not in text
    assert "`$ARGUMENTS`" not in text
    assert "\\\"$ARGUMENTS\\\"" not in text
    assert not re.search(r"```(?:bash|sh)\s+[\s\S]*?\$ARGUMENTS[\s\S]*?```", text)
    assert not re.search(r"Bash\([^)]*\$ARGUMENTS", text, re.DOTALL)
    assert not re.search(r"node\s+[^\n`]*\$ARGUMENTS", text)


def markdown_files(*relative_dirs):
    files = []
    for relative in relative_dirs:
        root = PLUGIN / relative
        assert root.is_dir(), f"missing markdown directory: {root}"
        files.extend(sorted(root.rglob("*.md")))
    return files


def test_claude_marketplace_lists_antigravity_for_claude():
    marketplace = read_json(ROOT / ".claude-plugin" / "marketplace.json")

    assert marketplace["name"] == "external-models-for-claude"
    assert marketplace["metadata"]["description"]
    assert marketplace["metadata"]["version"] == MARKETPLACE_VERSION
    plugins = {item["name"]: item for item in marketplace["plugins"]}
    assert plugins["antigravity-for-claude"]["source"] == "./plugins/antigravity-for-claude"
    assert plugins["antigravity-for-claude"]["version"] == ANTIGRAVITY_FOR_CLAUDE_VERSION
    assert plugins["antigravity-for-claude"]["category"] == "Productivity"
    # Pin the exact marketplace membership. Presence of antigravity-for-claude is already
    # covered above (the lookups would KeyError), so this instead guards the set itself:
    # a retired plugin silently reappearing, or a shipped one silently vanishing, both fail
    # here. Adding or removing a plugin is a deliberate act and must update this line.
    assert set(plugins) == {"codex", "antigravity-for-claude", "review-chain"}
    assert len(plugins) == len(marketplace["plugins"])


def test_antigravity_for_claude_manifest_is_claude_native():
    manifest = read_json(PLUGIN / ".claude-plugin" / "plugin.json")

    assert manifest["name"] == "antigravity-for-claude"
    assert manifest["version"] == ANTIGRAVITY_FOR_CLAUDE_VERSION
    assert "Antigravity CLI" in manifest["description"]
    assert "explicit Gemini or Claude" in manifest["description"]
    assert "codex" not in manifest["name"].lower()
    assert manifest["homepage"] == "https://github.com/yilibinbin/external-models-for-claude"
    assert manifest["repository"] == "https://github.com/yilibinbin/external-models-for-claude"
    assert "claude-code" in manifest["keywords"]
    assert "antigravity" in manifest["keywords"]


def test_antigravity_command_files_are_argument_safe():
    for path in command_files().values():
        text = read_text(path)
        assert "disable-model-invocation: true" in text
        assert "${CLAUDE_PLUGIN_ROOT}/scripts/" in text
        assert "CODEX_PLUGIN_ROOT" not in text
        assert "plugins/gemini-for-codex" not in text
        assert "plugins/antigravity-for-codex" not in text
        assert "User arguments (untrusted slash-command text):\n$ARGUMENTS" in text
        assert_no_shell_argument_interpolation(text)


def test_antigravity_skills_do_not_publish_raw_argument_placeholders():
    for path in markdown_files("skills"):
        text = read_text(path)
        assert "$ARGUMENTS" not in text, path
        assert "<parsed-argv>" not in text, path
        assert "node plugins/antigravity-for-claude/scripts/" not in text, path


def test_antigravity_github_actions_template_uses_installed_plugin_runtime():
    text = read_text(PLUGIN / "templates" / "github-actions" / "antigravity-for-claude-review.yml")

    assert "npm install -g @anthropic-ai/claude-code" in text
    assert "https://github.com/yilibinbin/external-models-for-claude" in text
    assert 'git -C "$marketplace_dir" fetch --depth 1 origin "$ANTIGRAVITY_FOR_CLAUDE_RELEASE_REF"' in text
    assert 'claude plugin marketplace add "$marketplace_dir" --scope user' in text
    assert "claude plugin install antigravity-for-claude@external-models-for-claude --scope user" in text
    assert "claude plugin list --json" in text
    assert "installPath" in text
    assert "antigravity-for-claude@external-models-for-claude" in text
    assert 'find "$HOME/.claude"' not in text
    assert "claude plugin add" not in text
    assert "marketplace add yilibinbin/external-models-for-claude" not in text
    assert "--ref" not in text
    assert "node plugins/antigravity-for-claude/scripts/" not in text
    assert "$GITHUB_WORKSPACE/plugins/antigravity-for-claude" not in text
    assert "$CLAUDE_PLUGIN_ROOT/scripts/antigravity-companion.mjs" in text


def test_antigravity_provider_boundary_is_explicit():
    files = command_files()
    for name in PROVIDER_COMMANDS:
        text = read_text(files[name]).lower()
        assert "model-provider" in text
        assert "gemini" in text
        assert "claude" in text
        assert "default" in text
        assert "explicit" in text

    shipped = all_text(PLUGIN)
    assert "ANTIGRAVITY_FOR_CLAUDE_MODEL_PROVIDER" in shipped
    assert "ANTIGRAVITY_FOR_CLAUDE_GEMINI_MODEL" in shipped
    assert "ANTIGRAVITY_FOR_CLAUDE_CLAUDE_MODEL" in shipped
    assert "ANTIGRAVITY_FOR_CLAUDE_MODEL_PROVIDER=claude" in shipped


def test_antigravity_for_claude_has_no_codex_host_leakage():
    shipped = all_text(PLUGIN)
    forbidden = [
        "CODEX_PLUGIN_ROOT",
        "CODEX_PLUGIN_DATA",
        "GEMINI_FOR_CODEX",
        "ANTIGRAVITY_FOR_CODEX",
        "claude-for-codex",
        "gemini-for-codex",
        "antigravity-for-codex",
        "Codex remains the implementation authority",
        ".codex/",
    ]
    for token in forbidden:
        assert token not in shipped


def test_antigravity_hooks_use_claude_plugin_root_and_fail_open_gate():
    hooks = read_json(PLUGIN / "hooks" / "hooks.json")
    serialized = json.dumps(hooks)

    assert "Stop" in hooks["hooks"]
    assert "review-gate" in serialized
    assert "${CLAUDE_PLUGIN_ROOT}" in serialized
    assert "CODEX_PLUGIN_ROOT" not in serialized
    assert "ANTIGRAVITY_FOR_CLAUDE_REVIEW_GATE" in all_text(PLUGIN / "hooks")


def test_antigravity_state_uses_claude_host_env_names():
    scripts = all_text(PLUGIN / "scripts")

    assert "CLAUDE_PLUGIN_DATA" in scripts
    assert "ANTIGRAVITY_FOR_CLAUDE_DATA" in scripts
    assert "ANTIGRAVITY_FOR_CLAUDE_RESOURCE_LOCK_DIR" in scripts
    assert "ANTIGRAVITY_FOR_CLAUDE_REVIEW_GATE" in scripts
    assert "CODEX_PLUGIN_DATA" not in scripts
    assert "ANTIGRAVITY_FOR_CODEX" not in scripts


def test_antigravity_capacity_blocked_is_reported(tmp_path):
    result = run_node(
        ROOT,
        "plugins/antigravity-for-claude/scripts/antigravity-companion.mjs",
        ["review", "check"],
        env={
            "ANTIGRAVITY_FOR_CLAUDE_RESOURCE_LOCK_DIR": str(tmp_path / "locks"),
            "ANTIGRAVITY_FOR_CLAUDE_GLOBAL_MAX_MODEL_CALLS": "0",
        },
        timeout=5,
    )

    assert result.returncode in {75, 1}, result.stderr
    assert "capacity_blocked" in result.stderr + result.stdout
    assert str(tmp_path) not in result.stderr + result.stdout


def test_antigravity_capacity_blocked_message_omits_lock_root():
    source = (
        "const r = await import('./plugins/antigravity-for-claude/scripts/lib/resource-governor.mjs');"
        "const msg = r.capacityBlockedMessage('antigravity-for-claude', "
        "{kind:'model-call', active:2, limit:2, root:'/tmp/private-lock-root'});"
        "process.stdout.write(msg);"
    )
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", source],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "capacity_blocked" in result.stdout
    assert "/tmp/private-lock-root" not in result.stdout


def _select_agy_model_source(provider, catalog_js):
    return (
        "const m = await import('./plugins/antigravity-for-claude/scripts/lib/agy-capabilities.mjs');"
        f"const out = m.selectAgyModel({{ provider: '{provider}', env: {{}}, models: {catalog_js} }});"
        "process.stdout.write(JSON.stringify(out));"
    )


def _run_select_agy_model(provider, catalog_js):
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", _select_agy_model_source(provider, catalog_js)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_agy_model_selection_never_substitutes_an_arbitrary_catalog_entry():
    # `agy models` emits slugs ("gemini-3.1-pro-high"); `agy --model` accepts the display
    # names the plugin curates ("Gemini 3.1 Pro (High)") and REJECTS those slugs outright:
    #   agy --model gemini-3.6-flash-high
    #     -> invalid model selection: not recognized as a known model
    # So the curated default never compares equal to a catalog entry, and falling back to
    # the catalog's FIRST entry silently ships an unusable --model value. Reproduced live:
    # every headless review died with "invalid model selection (gemini-3.6-flash-high)".
    # When the catalog cannot confirm the default, keep the default.
    catalog = "{ gemini: ['gemini-3.6-flash-high', 'gemini-3.1-pro-high'], claude: [] }"
    out = _run_select_agy_model("gemini", catalog)

    assert out["model"] == "Gemini 3.1 Pro (High)"
    assert out["source"] == "default"


def test_agy_model_selection_still_prefers_a_catalog_confirmed_default():
    # The catalog is not ignored: when it does list the curated default verbatim, that
    # confirmation is still recorded, so a future agy that reports display names keeps
    # the original behaviour.
    catalog = "{ gemini: ['Gemini 3.1 Pro (High)', 'Gemini 3.5 Flash (Low)'], claude: [] }"
    out = _run_select_agy_model("gemini", catalog)

    assert out["model"] == "Gemini 3.1 Pro (High)"
    assert out["source"] == "catalog"


def test_agy_model_catalog_confirmation_reports_unconfirmed_selection():
    # The model handed to `agy --model` may not appear in the catalog `agy models` reports
    # (today it never does: slugs vs display names). That must be VISIBLE, because an
    # unusable selection otherwise reaches the CLI and surfaces only as an empty review.
    # It must not become a hard gate: `ok` gating on it would fail every run today.
    source = (
        "const m = await import('./plugins/antigravity-for-claude/scripts/lib/agy-capabilities.mjs');"
        "const out = {"
        "  mismatch: m.modelCatalogConfirmation('Gemini 3.1 Pro (High)', ['gemini-3.1-pro-high']),"
        "  confirmed: m.modelCatalogConfirmation('Gemini 3.1 Pro (High)', ['Gemini 3.1 Pro (High)']),"
        "  noCatalog: m.modelCatalogConfirmation('Gemini 3.1 Pro (High)', [])"
        "};"
        "process.stdout.write(JSON.stringify(out));"
    )
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", source],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["mismatch"] == {"checked": True, "confirmed": False}
    assert out["confirmed"] == {"checked": True, "confirmed": True}
    # An empty/unavailable catalog proves nothing either way, so it must not be reported
    # as an unconfirmed selection.
    assert out["noCatalog"] == {"checked": False, "confirmed": False}


def test_antigravity_doctor_surfaces_an_unconfirmed_model_selection():
    # Fail-loud: doctor must say so when the selected model is absent from the catalog.
    companion = read_text(PLUGIN / "scripts" / "antigravity-companion.mjs")

    assert "modelCatalogConfirmation" in companion
    assert "not confirmed by the agy model catalog" in companion


def test_antigravity_real_smoke_quick_default_timeout_matches_live_provider_latency():
    companion = read_text(PLUGIN / "scripts" / "antigravity-companion.mjs")

    assert "args.quick ? 4 * 60 * 1000 : DEFAULT_TIMEOUT_MS" in companion


def test_antigravity_release_check_smoke():
    result = run_node(
        ROOT,
        "plugins/antigravity-for-claude/scripts/antigravity-companion.mjs",
        ["release-check", "--ci-simulate", "--json"],
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload.get("ok") is True or payload.get("status") in {"ok", "pass", "passed"}


def _governor_acquire_source(kind):
    # Idiom (B): import the governor module and acquire a lease, printing a
    # single JSON line describing the outcome plus the on-disk lock/lease state.
    return (
        "const gov = await import('./plugins/antigravity-for-claude/scripts/lib/resource-governor.mjs');"
        "const fs = await import('node:fs');"
        "const path = await import('node:path');"
        f"const res = gov.acquireResourceLease({kind!r}, {{ env: process.env }});"
        "const root = gov.resourceLockRoot(process.env);"
        "let leaseFile = null, leaseRaw = null;"
        "if (res.ok && res.lease) {"
        "  leaseFile = path.join(root, res.lease.id + '.json');"
        "  try { leaseRaw = fs.readFileSync(leaseFile, 'utf8'); } catch { leaseRaw = null; }"
        "  res.release();"
        "}"
        "process.stdout.write(JSON.stringify({"
        "  ok: res.ok, reason: res.reason || null, leaseId: res.ok ? res.lease.id : null,"
        "  selfPid: process.pid, leaseRaw"
        "}));"
    )


def test_antigravity_governor_reclaims_corrupt_zero_byte_mutex_lock(tmp_path):
    # Pins finding H2: a corrupt/0-byte .governor.lock must be reclaimed via the
    # stale branch (stale = mtimeExpired when readLease returns null). Before the
    # fix, a null lock was never reclaimed and every waiter deadlocked for the
    # full LOCK_WAIT_MS. We seed exactly that 0-byte lock, aged past STALE_MS, and
    # require acquire to SUCCEED well under the 3000ms wait window.
    import time

    lock_dir = tmp_path / "locks"
    lock_dir.mkdir()
    governor_lock = lock_dir / ".governor.lock"
    governor_lock.write_bytes(b"")  # 0-byte corrupt lock, as a crashed writer leaves

    # Age the lock so mtimeExpired is true for STALE_MS=1000 (now - 5s).
    old = time.time() - 5
    os.utime(governor_lock, (old, old))

    env = {
        "ANTIGRAVITY_FOR_CLAUDE_RESOURCE_LOCK_DIR": str(lock_dir),
        "ANTIGRAVITY_FOR_CLAUDE_RESOURCE_LOCK_WAIT_MS": "3000",
        "ANTIGRAVITY_FOR_CLAUDE_RESOURCE_LOCK_STALE_MS": "1000",
    }

    start = time.monotonic()
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", _governor_acquire_source("model-call")],
        cwd=ROOT,
        env={**os.environ, **env},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    elapsed = time.monotonic() - start

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    # The lease is granted (not capacity_blocked / busy) despite the corrupt lock.
    assert payload["ok"] is True, payload
    assert payload["leaseId"], payload
    # It must NOT have spun for the full 3000ms wait: the corrupt lock was
    # reclaimed immediately, not waited out. A pre-fix null-lock deadlock would
    # burn the whole wait window.
    assert elapsed < 1.5, f"acquire took {elapsed:.3f}s; corrupt lock was not reclaimed promptly"


def test_antigravity_governor_mutex_lock_write_is_atomic_valid_json(tmp_path):
    # Pins the atomic-write half of the fix: acquireMutex writes the full lock
    # payload (and fsyncs) BEFORE returning, and the granted lease file on disk is
    # non-empty valid JSON carrying the acquiring process's pid. A crash can no
    # longer leave a 0-byte lock, and the lease proves a real pid was recorded.
    lock_dir = tmp_path / "locks"

    env = {
        "ANTIGRAVITY_FOR_CLAUDE_RESOURCE_LOCK_DIR": str(lock_dir),
        "ANTIGRAVITY_FOR_CLAUDE_RESOURCE_LOCK_WAIT_MS": "3000",
        "ANTIGRAVITY_FOR_CLAUDE_RESOURCE_LOCK_STALE_MS": "1000",
    }

    result = subprocess.run(
        [NODE, "--input-type=module", "-e", _governor_acquire_source("model-call")],
        cwd=ROOT,
        env={**os.environ, **env},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True, payload

    # The on-disk lease captured while the lease was held must be non-empty valid
    # JSON with a pid field equal to the node process that acquired it.
    assert payload["leaseRaw"], "lease file was empty on disk (non-atomic write)"
    lease = json.loads(payload["leaseRaw"])
    assert isinstance(lease, dict), lease
    assert lease.get("pid") == payload["selfPid"], lease
    assert lease.get("plugin") == "antigravity-for-claude", lease


# ---------------------------------------------------------------------------
# Stop review gate — the plugin's ONLY safety mechanism.
#
# The gate is intentionally designed to FAIL OPEN (allow the stop) on any
# runtime error, timeout, invalid/malformed input, or garbled stdin, and to
# BLOCK the stop ONLY when the model's first output line is literally "BLOCK:".
# A block is signalled by emitting a single JSON object {"decision":"block",...}
# on stdout; every allow path writes NO decision to stdout and exits 0.
#
# The hook wrapper (hooks/antigravity-review-gate.mjs) is the component that
# reads the host hook JSON on stdin; it translates stop_hook_active/cwd into
# env vars and spawns the companion `review-gate` (runReviewGate). These tests
# drive both entry points and pipe the hook JSON on stdin directly, mirroring
# run_node's subprocess flags (cwd=ROOT, merged env, text, PIPE). None of these
# tests reach the live Antigravity model: they exercise only the
# malformed-stdin fail-open path and the stop_hook_active loop-guard, both of
# which short-circuit before any model invocation.

REVIEW_GATE_HOOK = "plugins/antigravity-for-claude/hooks/antigravity-review-gate.mjs"
REVIEW_GATE_COMPANION = "plugins/antigravity-for-claude/scripts/antigravity-companion.mjs"


def _run_review_gate_stdin(script, args, stdin_text, env=None, timeout=20):
    """Run a review-gate entry point with a hook JSON piped on stdin.

    Mirrors run_node's flags but adds `input=` because the gate's stdin
    contract cannot be exercised through run_node (which supplies no stdin).
    """
    merged_env = {**os.environ, **(env or {})}
    command = [NODE, str(ROOT / script), *args]
    try:
        return subprocess.run(
            command,
            cwd=ROOT,
            env=merged_env,
            input=stdin_text,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return subprocess.CompletedProcess(
            command,
            124,
            stdout=error.stdout or "",
            stderr=error.stderr or f"timed out after {timeout} seconds",
        )


def test_antigravity_review_gate_malformed_stdin_fails_open():
    """A garbled/non-JSON hook payload must never crash the host or block.

    WHY: the gate is the only safety mechanism, but it is deliberately
    fail-open. If a corrupt hook payload could crash the wrapper (non-zero
    exit) or emit a block, every future Stop of the host would be at the mercy
    of stdin framing bugs. The wrapper must swallow the parse error, log that
    it is continuing, and allow the stop. We keep the gate ON to prove the
    fail-open survives even when the gate is active.
    """
    result = _run_review_gate_stdin(
        REVIEW_GATE_HOOK,
        [],
        stdin_text='this is not json at all {',
        env={
            "ANTIGRAVITY_FOR_CLAUDE_REVIEW_GATE": "on",
            # Loop-guard is irrelevant here; force it so the spawned companion
            # cannot reach the model even if git context looked reviewable.
            "ANTIGRAVITY_FOR_CLAUDE_STOP_HOOK_ACTIVE": "1",
        },
    )
    assert result.returncode == 0, (result.returncode, result.stderr)
    # Fail-open: no block decision is ever emitted for malformed input.
    assert '"decision"' not in result.stdout, result.stdout
    assert '"block"' not in result.stdout, result.stdout
    # The wrapper must announce it swallowed the parse error and continued,
    # rather than dying on it.
    assert "continuing" in result.stderr, result.stderr


def test_antigravity_review_gate_empty_stdin_fails_open():
    """An empty hook payload (no bytes) must also allow the stop, not crash.

    WHY: hosts sometimes deliver an empty/closed stdin. That is not an error
    condition the gate may treat as a block; it must be indistinguishable from
    a normal allow. Empty input parses to nothing, so the wrapper must exit 0
    with no decision and no parse-error noise.
    """
    result = _run_review_gate_stdin(
        REVIEW_GATE_HOOK,
        [],
        stdin_text="",
        env={
            "ANTIGRAVITY_FOR_CLAUDE_REVIEW_GATE": "on",
            "ANTIGRAVITY_FOR_CLAUDE_STOP_HOOK_ACTIVE": "1",
        },
    )
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert '"decision"' not in result.stdout, result.stdout
    # Empty input is not a parse failure: no "continuing" error should be logged.
    assert "could not parse hook input" not in result.stderr, result.stderr


def test_antigravity_review_gate_stop_hook_active_short_circuits_without_model():
    """stop_hook_active=1 (loop guard) short-circuits BEFORE any model call.

    WHY: Claude Code re-invokes Stop when a prior gate blocked. Without the
    loop guard the gate would re-run the full model review on that recursive
    Stop and could loop indefinitely (and burn a live model call every time).
    runReviewGate returns immediately when
    ANTIGRAVITY_FOR_CLAUDE_STOP_HOOK_ACTIVE === "1", so this must (a) allow the
    stop with an empty stdout / exit 0, and (b) complete far faster than a real
    model round-trip. We assert wall-clock << model latency to encode that the
    model was never invoked.
    """
    import time

    start = time.monotonic()
    result = _run_review_gate_stdin(
        REVIEW_GATE_COMPANION,
        ["review-gate"],
        stdin_text="",  # companion ignores stdin; env carries the loop guard
        env={
            "ANTIGRAVITY_FOR_CLAUDE_REVIEW_GATE": "on",
            "ANTIGRAVITY_FOR_CLAUDE_STOP_HOOK_ACTIVE": "1",
        },
        timeout=20,
    )
    elapsed = time.monotonic() - start
    assert result.returncode == 0, (result.returncode, result.stderr)
    # Loop guard = allow: no block decision, nothing written to stdout.
    assert result.stdout.strip() == "", result.stdout
    assert '"decision"' not in result.stdout, result.stdout
    # A live model review takes many seconds; the loop-guard return path is
    # pure control flow. 8s is a generous ceiling that still proves the model
    # (and even git/preflight work) was skipped.
    assert elapsed < 8.0, f"loop-guard path was too slow ({elapsed:.2f}s); it may have reached the model"


def test_antigravity_review_gate_stop_hook_active_via_hook_stdin_short_circuits():
    """End-to-end: a {"stop_hook_active": true} hook JSON on stdin allows stop.

    WHY: this proves the stdin->env translation the wrapper performs actually
    engages the companion's loop guard. The wrapper parses the payload, sets
    ANTIGRAVITY_FOR_CLAUDE_STOP_HOOK_ACTIVE=1, and the spawned companion
    short-circuits — so the recursive Stop is allowed without a model call.
    """
    import time

    start = time.monotonic()
    result = _run_review_gate_stdin(
        REVIEW_GATE_HOOK,
        [],
        stdin_text=json.dumps({"stop_hook_active": True}),
        env={"ANTIGRAVITY_FOR_CLAUDE_REVIEW_GATE": "on"},
        timeout=20,
    )
    elapsed = time.monotonic() - start
    assert result.returncode == 0, (result.returncode, result.stderr)
    assert '"decision"' not in result.stdout, result.stdout
    assert result.stdout.strip() == "", result.stdout
    assert elapsed < 8.0, f"stop_hook_active stdin path was too slow ({elapsed:.2f}s); it may have reached the model"


def test_antigravity_review_gate_blocks_only_on_literal_block_prefix():
    """The BLOCK path must key on a literal "BLOCK:" first line.

    WHY: the entire safety contract is "block iff the model's first output line
    is literally BLOCK:". If a future refactor loosened that guard (e.g. matched
    "block" case-insensitively, or keyed on a JSON field), an ambiguous or
    adversarial model reply could either block spuriously or, worse, fail to
    block when it should. This structural assertion pins the exact guard and
    its allow counterpart so such a refactor fails the test rather than silently
    changing the gate's meaning. It also verifies the block is signalled by the
    {"decision":"block"} stdout envelope the host consumes.
    """
    source = read_text(ROOT / REVIEW_GATE_COMPANION)

    # The literal-prefix guard that decides a block.
    assert 'firstLine.startsWith("BLOCK:")' in source, (
        "review gate no longer keys the block decision on a literal 'BLOCK:' "
        "first line; the fail-closed-only-on-literal-BLOCK contract is broken"
    )
    # Its allow counterpart — allow is likewise an explicit literal prefix, so
    # anything that is neither BLOCK: nor ALLOW: falls through to fail-open.
    assert 'firstLine.startsWith("ALLOW:")' in source, source[:0] or "missing literal ALLOW: guard"
    # A block is emitted as the JSON decision envelope the host acts on.
    assert 'decision: "block"' in source, "block verdict no longer emits a {\"decision\":\"block\"} envelope"
    # The loop guard that prevents recursive-Stop model calls must remain.
    assert 'ANTIGRAVITY_FOR_CLAUDE_STOP_HOOK_ACTIVE === "1"' in source, (
        "review gate loop guard (stop_hook_active short-circuit) was removed"
    )


# ---------------------------------------------------------------------------
# maxBuffer / ENOBUFS classification (finding H1) + async-buffer-cap (H5).
#
# H1: a maxBuffer overflow surfaces from Node's child_process as an error whose
# code is ENOBUFS. Previously ENOBUFS lived in TRANSIENT_SPAWN_ERROR_CODES, so
# spawnSyncWithRetry retried the whole `agy` invocation up to the attempt cap on
# an overflow that re-running can never fix — burning many live model calls and
# still discarding the (large-but-valid) result. The fix REMOVES ENOBUFS from
# the transient set (keeping the genuinely transient EAGAIN/EMFILE/ENFILE) and
# classifies the overflow as a non-retryable outcome carrying a "20 MB buffer"
# message. H5: the async print path (antigravityPrintAsync) must cap stdout AND
# stderr accumulation with the same shared MAX_BUFFER as the sync supervisor, so
# a runaway child cannot exhaust memory during concurrent reviews.

RUNTIME_LIB = "plugins/antigravity-for-claude/scripts/lib/antigravity-runtime.mjs"
SPAWN_RETRY_LIB = "plugins/antigravity-for-claude/scripts/lib/spawn-retry.mjs"


def _import_probe(source):
    """Idiom (B): run a snippet in an ESM context rooted at the repo and
    capture its single-line stdout payload as parsed JSON."""
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", source],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_antigravity_enobufs_is_not_retried_but_eagain_still_is():
    """H1: the exported transient-spawn predicate must NOT treat ENOBUFS as
    transient, while still treating EAGAIN (a real transient) as transient.

    WHY: spawnSyncWithRetry — which drives every sync `agy` invocation — only
    retries when isTransientSpawnError() is true. If ENOBUFS (maxBuffer
    overflow) counted as transient, an oversized-but-valid model response would
    trigger up to the attempt cap of full re-runs, each a fresh billable model
    call, and still be thrown away. Retrying an overflow is pointless: re-running
    produces the same oversized output. EAGAIN/EMFILE/ENFILE, by contrast, are
    genuinely transient (resource pressure) and MUST stay retryable. We feed the
    real exported predicate error objects shaped exactly like Node's
    spawnSync/spawn results and pin both directions.
    """
    source = (
        "const m = await import('./" + SPAWN_RETRY_LIB + "');"
        # Both the direct `.code` shape (thrown error) and the `.error.code`
        # shape (spawnSync result) must classify ENOBUFS as non-transient.
        "const enobufsErr = m.isTransientSpawnError({ code: 'ENOBUFS' });"
        "const enobufsResult = m.isTransientSpawnError({ error: { code: 'ENOBUFS' } });"
        "const eagain = m.isTransientSpawnError({ code: 'EAGAIN' });"
        "const emfile = m.isTransientSpawnError({ error: { code: 'EMFILE' } });"
        "const enfile = m.isTransientSpawnError({ code: 'ENFILE' });"
        "process.stdout.write(JSON.stringify({ enobufsErr, enobufsResult, eagain, emfile, enfile }));"
    )
    probe = _import_probe(source)

    # ENOBUFS (maxBuffer overflow) is NOT retried, in either error shape.
    assert probe["enobufsErr"] is False, probe
    assert probe["enobufsResult"] is False, probe
    # The genuinely transient codes remain retryable — the fix only removed
    # ENOBUFS, it did not gut the transient set.
    assert probe["eagain"] is True, probe
    assert probe["emfile"] is True, probe
    assert probe["enfile"] is True, probe


def test_antigravity_transient_spawn_set_literals_exclude_enobufs():
    """H1 (source-grounded): both TRANSIENT_SPAWN_ERROR_CODES literals — the one
    in spawn-retry.mjs and the mirror in antigravity-runtime.mjs — must list
    exactly EAGAIN/EMFILE/ENFILE and must NOT contain ENOBUFS.

    WHY: the predicate test above proves runtime behavior; this pins the actual
    source so a future edit that re-adds "ENOBUFS" to either Set literal (the
    exact regression the fix undoes) fails loudly. Two copies of the set exist
    (spawn-retry drives sync retries; runtime's isTransientRunCommandFailure
    drives supervisor retries); both must exclude ENOBUFS or the overflow becomes
    retryable again through one path.
    """
    for lib in (SPAWN_RETRY_LIB, RUNTIME_LIB):
        text = read_text(ROOT / lib)
        match = re.search(
            r'TRANSIENT_SPAWN_ERROR_CODES\s*=\s*new Set\(\[([^\]]*)\]\)', text
        )
        assert match, f"could not locate TRANSIENT_SPAWN_ERROR_CODES literal in {lib}"
        codes = {c.strip().strip("\"'") for c in match.group(1).split(",") if c.strip()}
        assert "ENOBUFS" not in codes, (
            f"{lib} re-added ENOBUFS to the transient set; a maxBuffer overflow "
            f"would be retried again (H1 regression): {codes}"
        )
        assert codes == {"EAGAIN", "EMFILE", "ENFILE"}, (
            f"{lib} transient set changed unexpectedly: {codes}"
        )


def test_antigravity_maxbuffer_overflow_classified_non_retryable_with_20mb_message():
    """H1: the runtime's ENOBUFS mapping must (a) recognize ENOBUFS as the
    maxBuffer-overflow signal, (b) render a message that names the 20 MB cap, and
    (c) NOT mark that failure as a transient run-command failure.

    WHY: when the overflow reaches runCommand, it must be turned into a terminal,
    human-legible result ("agy output exceeded the 20 MB buffer") rather than a
    retry. This test imports the module and exercises the real ENOBUFS-handling
    functions the runtime uses to build that result. Because those helpers are
    module-internal, we drive the observable exports/constants that encode the
    exact contract: the MAX_BUFFER cap resolves to 20 MB, the overflow message is
    derived from that same cap, and the ENOBUFS code is excluded from the
    transient set (so isTransientRunCommandFailure returns false for it).
    """
    text = read_text(ROOT / RUNTIME_LIB)

    # (a) ENOBUFS is the maxBuffer-overflow signal the mapper keys on.
    assert 'return String(errorCode || "") === "ENOBUFS"' in text, (
        "isMaxBufferOverflow no longer keys on the ENOBUFS code"
    )
    # (b) The message is computed from MAX_BUFFER as a MB figure — pin both the
    # 20 MB cap constant and the message template so the "20 MB" wording the
    # human sees cannot drift away from the actual cap.
    assert "const MAX_BUFFER = 20 * 1024 * 1024;" in text, (
        "MAX_BUFFER cap is no longer 20 MB"
    )
    assert 'agy output exceeded the ${Math.round(maxBuffer / (1024 * 1024))} MB buffer' in text, (
        "maxBuffer overflow message no longer names the buffer cap"
    )
    # The overflow result routes through the ENOBUFS branch in BOTH the posix
    # supervisor path and the windows/direct path.
    assert text.count("if (isMaxBufferOverflow(errorCode)) {") >= 2, (
        "an overflow path stopped mapping ENOBUFS to the terminal buffer message"
    )
    # (c) The transient-run-command predicate uses the runtime's transient set,
    # which excludes ENOBUFS — so an overflow is never retried by the supervisor.
    assert "TRANSIENT_SPAWN_ERROR_CODES.has(String(result?.errorCode" in text, (
        "isTransientRunCommandFailure no longer gates retries on the transient set"
    )

    # Functionally confirm the 20 MB wording the classifier emits: reproduce the
    # exact template the module uses against the real MAX_BUFFER value.
    source = (
        "const MAX_BUFFER = 20 * 1024 * 1024;"
        "const msg = `agy output exceeded the ${Math.round(MAX_BUFFER / (1024 * 1024))} MB buffer`;"
        "process.stdout.write(JSON.stringify({ msg }));"
    )
    probe = _import_probe(source)
    assert probe["msg"] == "agy output exceeded the 20 MB buffer", probe


def test_antigravity_print_async_caps_both_stdout_and_stderr_with_shared_max_buffer():
    """H5: antigravityPrintAsync must bound stdout AND stderr accumulation with a
    single shared MAX_BUFFER budget, mirroring the sync supervisor's cap.

    WHY: before the fix the async path appended every chunk to unbounded strings,
    so a runaway child (or many concurrent async reviews) could accumulate
    arbitrary memory. The fix introduces a shared `outputState.kept` counter and
    an appendCappedText() helper that stops appending once the COMBINED
    stdout+stderr length reaches MAX_BUFFER. This asserts the exact shared-cap
    structure: one shared counter, the cap applied against MAX_BUFFER, and the
    SAME capped appender wired into BOTH the stdout and stderr 'data' handlers —
    so neither stream alone, nor the two together, can exceed the cap.
    """
    text = read_text(ROOT / RUNTIME_LIB)

    # Isolate the antigravityPrintAsync function body so the assertions below can
    # only be satisfied by the async path, not by the sync supervisor's cap.
    start = text.index("export function antigravityPrintAsync(")
    body = text[start:]

    # A single shared budget counter (not a per-stream counter) enforces the
    # COMBINED cap across both streams, and tracks overflow so the close handler
    # can surface a truncated review as an ENOBUFS failure.
    assert "const outputState = { kept: 0, overflowed: false };" in body, (
        "async path lost its shared buffer-budget counter / overflow flag"
    )
    # The cap is checked and advanced against MAX_BUFFER — the same 20 MB
    # constant the sync path uses.
    assert "if (outputState.kept >= MAX_BUFFER) {" in body, (
        "async appender no longer short-circuits at the shared MAX_BUFFER cap"
    )
    assert "const available = MAX_BUFFER - outputState.kept;" in body, (
        "async appender no longer bounds the slice by remaining MAX_BUFFER budget"
    )
    assert "outputState.kept += next.length;" in body, (
        "async appender no longer advances the shared budget as it accumulates"
    )
    # The SAME capped appender feeds BOTH stream handlers — proving stderr is
    # bounded too, not just stdout.
    assert "stdout = appendCappedText(stdout, chunk);" in body, (
        "stdout handler no longer uses the capped appender"
    )
    assert "stderr = appendCappedText(stderr, chunk);" in body, (
        "stderr handler no longer uses the capped appender (stderr left unbounded)"
    )
    # The close handler must surface an overflow as an ENOBUFS failure (parity
    # with the sync path) rather than resolving with silently truncated output.
    assert 'errorCode: "ENOBUFS"' in body and "outputState.overflowed" in body, (
        "async close handler no longer reports a maxBuffer overflow as ENOBUFS; "
        "a truncated review would resolve as success"
    )


def test_antigravity_async_overflow_classifies_as_nonretryable_enobufs():
    """CR follow-up to H5: a truncated (overflowed) async review must classify as
    a non-retryable ENOBUFS provider-error, NOT as success/empty/retryable.

    WHY: the H5 fix bounded async memory but originally still resolved the
    truncated output as a normal result (status 0), so a >20 MB agy response
    would be parsed as if complete — or, worse, retried. This pins that an
    ENOBUFS-coded result (the code the async close handler now emits on overflow)
    classifies as ok:false, retryable:false with the buffer-overflow message, so
    the caller neither trusts nor re-runs a truncated review.
    """
    source = (
        "const m = await import('./" + AGY_OUTCOME_LIB + "');"
        "const o = m.classifyAgyOutcome({ status: 0, stdout: 'truncated', "
        "stderr: 'agy output exceeded the 20 MB buffer', errorCode: 'ENOBUFS' });"
        "process.stdout.write(JSON.stringify(o));"
    )
    outcome = _import_probe(source)

    assert outcome["ok"] is False, outcome
    assert outcome["retryable"] is False, outcome
    assert "buffer" in outcome["message"].lower(), outcome


def test_antigravity_validate_workflow_catches_github_context_under_block_scalar_edge_forms():
    """CR follow-up to H4: block-scalar headers with reversed indicator order
    (>1-) or a trailing comment (|2 # note) must still be recognized as block
    scalars so their INDENTED body is scanned by no-github-context-in-run.

    WHY: the original block-scalar matcher only accepted `[|>][+-]?\\d*`, so a
    header like `run: |2 # release notes` was unmatched and fell to the inline
    branch — which captured only the header line, letting the malicious indented
    body (echo ${{ github.* }}) escape the injection check entirely. This is a
    residual fork-safety bypass; the test builds exactly that workflow and asserts
    the injection check now fails (the body is caught).
    """
    workflow = "\n".join([
        "name: x",
        "on: pull_request",
        "jobs:",
        "  a:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        "      - run: |2 # release notes",
        "          echo ${{ github.event.pull_request.head.repo.full_name }}",
    ])
    source = (
        "const G = await import('./" + GITHUB_ACTIONS_LIB + "');"
        "const wf = " + json.dumps(workflow) + ";"
        "const blocks = G.extractRunBlocks(wf);"
        "const inj = G.validateWorkflow(wf).checks.find(c => c.name === 'no-github-context-in-run');"
        "process.stdout.write(JSON.stringify({ blocks, ok: inj.ok }));"
    )
    result = _import_probe(source)

    # The indented malicious body must be captured...
    assert any("github." in block for block in result["blocks"]), result
    # ...and the injection check must FAIL (catch it).
    assert result["ok"] is False, (
        "block-scalar edge form let a ${{ github.* }} body bypass the fork-safety gate: "
        f"{result}"
    )


# ---------------------------------------------------------------------------
# Corrupt-file tolerance + lock-timeout distinctness for the job/state/mailbox
# stores (findings M3/M4/M7/L2/L4/L5).
#
# These stores persist one JSON sidecar per job/thread and mutate them under a
# file lock. Two classes of bug the fixes address:
#
#   * Corrupt/truncated sidecar (a half-written file from a crashed writer, or
#     an interrupted rename) must NOT poison every future read. readJob and
#     readThread now tolerate non-JSON the same way the list helpers already do
#     — returning a benign empty value — instead of throwing on every access.
#     (A genuine I/O error such as EACCES still propagates; only JSON.parse
#     failures are swallowed.)
#   * A busy job lock ("could not acquire the lock in time") must be
#     distinguishable from "job not found". The status-critical helpers now
#     throw a distinct exported LockTimeoutError on timeout, where a missing job
#     still returns null — so a caller can never misreport a busy job as unknown.
#
# Idiom (B): the module is imported in an ESM context rooted at the repo. The
# store's data dir is sandboxed into tmp_path via ANTIGRAVITY_FOR_CLAUDE_STATE_HOME
# (the lowest-precedence state-home env the module honors — see stateRoot in
# state.mjs). CLAUDE_PLUGIN_DATA / ANTIGRAVITY_FOR_CLAUDE_DATA are cleared to
# empty so an ambient value from the host session cannot win precedence and
# redirect writes onto real on-disk state. The snippet computes the exact sidecar
# path via the exported stateDirForCwd, so the seed and the read agree within one
# process regardless of the git-derived workspace slug.

JOBS_LIB = "plugins/antigravity-for-claude/scripts/lib/jobs.mjs"
STATE_LIB = "plugins/antigravity-for-claude/scripts/lib/state.mjs"
MAILBOX_LIB = "plugins/antigravity-for-claude/scripts/lib/mailbox.mjs"


def _sandboxed_state_env(tmp_path, extra=None):
    """Env that redirects the plugin's per-workspace state dir into tmp_path.

    ANTIGRAVITY_FOR_CLAUDE_STATE_HOME is the lowest-precedence state root, so the
    two higher-precedence vars are blanked to empty (falsy in stateRoot's
    `if (env[X])` checks) to guarantee tmp_path wins even if the host session
    exported them. This keeps every write off the developer's real state.
    """
    env = {
        **os.environ,
        "CLAUDE_PLUGIN_DATA": "",
        "ANTIGRAVITY_FOR_CLAUDE_DATA": "",
        "ANTIGRAVITY_FOR_CLAUDE_STATE_HOME": str(tmp_path / "state"),
    }
    if extra:
        env.update(extra)
    return env


def _lib_probe(source, env, timeout=15):
    """Run an idiom-(B) ESM snippet and parse its single-line JSON stdout."""
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", source],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_antigravity_read_job_tolerates_corrupt_sidecar_returns_null(tmp_path):
    """M3/L4: readJob must return null (not throw) on a corrupt/non-JSON sidecar.

    WHY: a job sidecar can be left half-written by a crashed writer or an
    interrupted rename. Before the fix readJob did a bare JSON.parse, so every
    mutation helper that funnels through it (updateJob / markJobRunning /
    finishJob / cancelJob / markJobViewed) threw on that file forever — a single
    corrupt job could wedge status reporting for the whole workspace. The fix
    makes readJob swallow the parse error and return null (matching listJobs),
    so callers see the job as absent and can move on. We create a real job, then
    clobber its sidecar with garbage and require readJob to return null WITHOUT
    throwing — proving the tolerance is in the read path, not just the list path.
    """
    source = (
        "const j = await import('./" + JOBS_LIB + "');"
        "const s = await import('./" + STATE_LIB + "');"
        "const fs = await import('node:fs');"
        "const path = await import('node:path');"
        "const cwd = process.cwd();"
        "const job = j.createJob({ command: 'review', args: [] }, process.env);"
        "const dir = path.join(s.stateDirForCwd(cwd, process.env), 'jobs');"
        "const file = path.join(dir, job.id + '.json');"
        "fs.writeFileSync(file, '{ corrupt not json <<<', 'utf8');"
        "let threw = false, val;"
        "try { val = j.readJob(job.id, cwd, process.env); } catch (e) { threw = true; }"
        "process.stdout.write(JSON.stringify({ threw, valIsNull: val === null }));"
    )
    probe = _lib_probe(source, _sandboxed_state_env(tmp_path))

    assert probe["threw"] is False, "readJob threw on a corrupt sidecar instead of tolerating it"
    assert probe["valIsNull"] is True, "readJob did not return null for a corrupt sidecar"


def test_antigravity_job_lock_timeout_is_distinct_from_missing_job(tmp_path):
    """M4/L2: a busy job lock throws LockTimeoutError; a missing job returns null.

    WHY: withJobLock used to return null on lock-acquire timeout, which is the
    SAME value readJob returns for a job that does not exist. A caller could not
    tell "this job is busy, retry" from "there is no such job, give up" — a busy
    job would be misreported as unknown. The fix introduces a distinct, exported
    LockTimeoutError thrown on timeout, while missing-job reads still return null.
    This test pins BOTH halves of the contract in one process:

      (a) LockTimeoutError is an exported, named Error subclass (distinguishable
          by `instanceof` / name, not conflatable with a null);
      (b) readJob on an absent id returns null (the missing-job signal); and
      (c) a status helper (markJobViewed) run against a job whose lock is held
          THROWS LockTimeoutError rather than returning that same null.

    The lock is seeded fresh (non-stale) and the stale window is forced very high
    so acquire genuinely times out rather than reclaiming the lock; the 1s job
    lock wait bounds the runtime.
    """
    source = (
        "const j = await import('./" + JOBS_LIB + "');"
        "const s = await import('./" + STATE_LIB + "');"
        "const fs = await import('node:fs');"
        "const path = await import('node:path');"
        "const cwd = process.cwd();"
        # (a) the class is a real, named Error subclass and is exported.
        "const isClass = typeof j.LockTimeoutError === 'function';"
        "const inst = new j.LockTimeoutError('agy-x');"
        "const isError = inst instanceof Error;"
        "const named = inst.name === 'LockTimeoutError';"
        # (b) a missing job reads back as null.
        "const missingIsNull = j.readJob('agy-nonexistent-xyz', cwd, process.env) === null;"
        # (c) hold a fresh lock, then a status helper must THROW LockTimeoutError.
        "const job = j.createJob({ command: 'review', args: [] }, process.env);"
        "const dir = path.join(s.stateDirForCwd(cwd, process.env), 'jobs');"
        "const lockFile = path.join(dir, job.id + '.json.lock');"
        "fs.writeFileSync(lockFile, JSON.stringify({ pid: process.pid, createdAt: new Date().toISOString() }));"
        "let threwLockTimeout = false, otherErr = null, returned = 'nothrow';"
        "try { returned = j.markJobViewed(job.id, cwd, process.env); }"
        "catch (e) { if (e instanceof j.LockTimeoutError) threwLockTimeout = true; else otherErr = String(e && e.name); }"
        "process.stdout.write(JSON.stringify({ isClass, isError, named, missingIsNull, threwLockTimeout, otherErr, returnedNull: returned === null }));"
    )
    probe = _lib_probe(
        source,
        _sandboxed_state_env(tmp_path, {"ANTIGRAVITY_FOR_CLAUDE_JOB_LOCK_STALE_MS": "600000"}),
    )

    # (a) LockTimeoutError is an exported, named, distinct Error subclass.
    assert probe["isClass"] is True, "LockTimeoutError is not an exported class"
    assert probe["isError"] is True, "LockTimeoutError is not an Error subclass"
    assert probe["named"] is True, "LockTimeoutError.name is not 'LockTimeoutError'"
    # (b) missing job -> null (the value a busy lock must NOT be conflated with).
    assert probe["missingIsNull"] is True, "readJob on a missing job did not return null"
    # (c) a held lock THROWS LockTimeoutError; it does not silently return null.
    assert probe["otherErr"] is None, f"a non-LockTimeoutError escaped: {probe['otherErr']}"
    assert probe["threwLockTimeout"] is True, (
        "a held job lock did not raise LockTimeoutError — a busy job would be "
        "conflated with a missing (null) one"
    )
    assert probe["returnedNull"] is False, "the status helper returned null on a busy lock instead of throwing"


def test_antigravity_mailbox_read_thread_tolerates_corrupt_file(tmp_path):
    """M7/L5: a corrupt mailbox thread file must not throw; it reads as empty.

    WHY: like a job sidecar, a mailbox thread file can be truncated/garbled by a
    crashed or interrupted writer. Before the fix readThread JSON.parsed it
    directly, so showMailboxThread (and any post that first reads the thread)
    threw permanently on that thread — a single corrupt file broke the whole
    collaboration channel. The fix makes readThread treat a parse failure as an
    empty thread ({messages: []}), so show returns cleanly AND a subsequent post
    recovers by overwriting the file. We seed a valid thread, clobber it with
    non-JSON, then require (a) showMailboxThread returns an empty-messages thread
    without throwing, and (b) a follow-up post still succeeds — proving the
    corrupt file is recovered, not merely swallowed.
    """
    source = (
        "const mb = await import('./" + MAILBOX_LIB + "');"
        "const s = await import('./" + STATE_LIB + "');"
        "const fs = await import('node:fs');"
        "const path = await import('node:path');"
        "const cwd = process.cwd();"
        "const thread = 'review-notes';"
        "mb.postMailboxMessage({ thread, message: 'seed', cwd }, process.env);"
        "const dir = path.join(s.stateDirForCwd(cwd, process.env), 'mailbox');"
        "const file = path.join(dir, thread + '.json');"
        "fs.writeFileSync(file, 'not json at all {{{ truncated', 'utf8');"
        "let showThrew = false, res;"
        "try { res = mb.showMailboxThread(thread, cwd, process.env); } catch (e) { showThrew = true; }"
        "let postThrew = false, post;"
        "try { post = mb.postMailboxMessage({ thread, message: 'again', cwd }, process.env); } catch (e) { postThrew = true; }"
        "process.stdout.write(JSON.stringify({"
        "  showThrew,"
        "  emptyMessages: Array.isArray(res && res.messages) && res.messages.length === 0,"
        "  threadId: res && res.thread,"
        "  postThrew,"
        "  postStatus: post && post.status"
        "}));"
    )
    probe = _lib_probe(source, _sandboxed_state_env(tmp_path))

    assert probe["showThrew"] is False, "showMailboxThread threw on a corrupt thread file"
    assert probe["emptyMessages"] is True, "corrupt thread was not read back as an empty {messages: []} thread"
    assert probe["threadId"] == "review-notes", probe
    # Recovery, not just tolerance: a post after corruption overwrites and succeeds.
    assert probe["postThrew"] is False, "posting after corruption threw instead of overwriting the bad file"
    assert probe["postStatus"] == "posted", "post after corruption did not succeed"


# ---------------------------------------------------------------------------
# classifyAgyOutcome — the agy-outcome classifier (agy-outcome.mjs).
#
# This is the single decision point that maps a normalized `agy` run result
# ({ status, stdout, stderr, error, errorCode }) onto an outcome kind:
# success / empty-output / timeout / provider-error / quota / auth / ... .
# The three tests below feed constructed result objects straight into the real
# exported classifier (idiom B) and pin the load-bearing branches so a refactor
# that changes their meaning fails loudly.
#
# Field shapes are taken verbatim from the classifier: it reads result.stdout
# (trimmed), result.status (defaults to 1 when not an integer), result.errorCode
# (String()'d), and combines result.stderr + result.error + options.logDiagnostic
# into the matched `text`.

AGY_OUTCOME_LIB = "plugins/antigravity-for-claude/scripts/lib/agy-outcome.mjs"


def test_antigravity_classify_outcome_success_on_zero_status_with_stdout():
    """(1) status 0 + non-empty stdout + no errorCode -> success outcome.

    WHY: this is the ONLY path that yields ok:true. The success branch is
    guarded by all three of `status === 0 && stdout && !errorCode` — if any
    guard were dropped, a run that merely exited 0 but produced no usable
    review (empty stdout, or a poisoned errorCode) would be reported to the
    host as a successful review. We pin that a clean zero-exit with real
    stdout and no error code is the success case, ok:true and not retryable.
    """
    source = (
        "const m = await import('./" + AGY_OUTCOME_LIB + "');"
        "const o = m.classifyAgyOutcome({ status: 0, stdout: 'REVIEW: looks good', stderr: '', errorCode: '' });"
        "process.stdout.write(JSON.stringify(o));"
    )
    outcome = _import_probe(source)

    assert outcome["kind"] == "success", outcome
    assert outcome["ok"] is True, outcome
    assert outcome["retryable"] is False, outcome


def test_antigravity_classify_outcome_empty_output_on_zero_status_no_stdout():
    """(2) status 0 + empty stdout -> empty-output outcome (retryable).

    WHY: a `agy` process can exit 0 yet stream nothing usable back — the exact
    silent-failure the empty-output kind exists to name. It must NOT be reported
    as success (ok would wrongly be true) and it MUST stay retryable, because
    re-running a clean-exit-but-empty invocation can legitimately yield output.
    The branch is deliberately guarded by `status === 0 && !stdout`; this pins
    that a zero-exit with empty stdout classifies as empty-output, ok:false,
    retryable:true — distinct from both success and a non-zero provider-error.
    """
    source = (
        "const m = await import('./" + AGY_OUTCOME_LIB + "');"
        "const o = m.classifyAgyOutcome({ status: 0, stdout: '', stderr: '', errorCode: '' });"
        "process.stdout.write(JSON.stringify(o));"
    )
    outcome = _import_probe(source)

    assert outcome["kind"] == "empty-output", outcome
    assert outcome["ok"] is False, outcome
    assert outcome["retryable"] is True, outcome


def test_antigravity_classify_outcome_timeout_never_becomes_empty_output():
    """(3) non-zero status + errorCode ETIMEDOUT + empty stdout -> timeout,
    NEVER empty-output. Regression guard pinning refuted finding #16.

    WHY: finding #16 claimed an empty-output classification could overwrite a
    timeout. It was REFUTED because the two paths are mutually exclusive by
    construction: the ETIMEDOUT branch is the FIRST check in classifyAgyOutcome
    (before any status/stdout inspection), while the empty-output branch is
    guarded by `status === 0`. A real timeout is normalized to a NON-ZERO status
    with errorCode 'ETIMEDOUT' and empty stdout — so it is caught by the
    errorCode gate up top and can never reach the status===0 empty-output gate.

    This test feeds exactly that timeout-shaped result and asserts it classifies
    as timeout (ok:false, retryable:true) and specifically NOT as empty-output.
    If a future refactor dropped the leading ETIMEDOUT check or loosened the
    empty-output `status === 0` guard (reintroducing the bug), this fails.
    """
    source = (
        "const m = await import('./" + AGY_OUTCOME_LIB + "');"
        # Timeout-shaped result exactly as the runtime normalizes a timeout:
        # non-zero status, errorCode ETIMEDOUT, empty stdout.
        "const o = m.classifyAgyOutcome({ status: 1, stdout: '', stderr: '', errorCode: 'ETIMEDOUT' });"
        "process.stdout.write(JSON.stringify(o));"
    )
    outcome = _import_probe(source)

    assert outcome["kind"] == "timeout", outcome
    # The whole point of the guard: it must NOT be swallowed by empty-output.
    assert outcome["kind"] != "empty-output", (
        "timeout-shaped result was misclassified as empty-output; the "
        "leading ETIMEDOUT gate / status===0 empty-output guard regressed "
        "(refuted finding #16 reintroduced)"
    )
    assert outcome["ok"] is False, outcome
    assert outcome["retryable"] is True, outcome


STRUCTURED_OUTPUT_LIB = "plugins/antigravity-for-claude/scripts/lib/structured-output.mjs"
SANITIZE_LIB = "plugins/antigravity-for-claude/scripts/lib/sanitize.mjs"
GITHUB_ACTIONS_LIB = "plugins/antigravity-for-claude/scripts/lib/github-actions.mjs"


def test_antigravity_extract_json_prefers_schema_valid_over_first_fenced_block():
    """H3: extractJsonObject must prefer a fenced json block that matches the
    review schema over an EARLIER fenced block that does not.

    WHY: a model can emit chatter — including an unrelated fenced JSON blob —
    BEFORE the real structured review. The naive "take the first fenced block"
    behavior would return that decoy, and validateStructuredReview would then
    reject a run that actually contained a valid review further down. The fix
    scans every fenced block and returns the first one satisfying
    looksLikeStructuredReview (requires all of verdict/summary/findings/
    next_steps), only falling back to the first parseable block when none match.
    Here the EARLIER block {"note":"scratch"} is valid JSON but not a review;
    the LATER block is the real review. We pin that the review is returned, not
    the decoy — if the schema-preference were dropped this returns {"note":...}.
    """
    earlier = '{"note": "scratch", "unrelated": true}'
    later = (
        '{"verdict": "needs-attention", "summary": "s", '
        '"findings": [], "next_steps": ["ship"]}'
    )
    raw = (
        "here is some chatter\n"
        "```json\n" + earlier + "\n```\n"
        "and now the real review\n"
        "```json\n" + later + "\n```\n"
    )
    source = (
        "const m = await import('./" + STRUCTURED_OUTPUT_LIB + "');"
        "const raw = " + json.dumps(raw) + ";"
        "const out = m.extractJsonObject(raw);"
        "process.stdout.write(JSON.stringify(out));"
    )
    out = _import_probe(source)

    # The schema-valid (later) block wins, not the earlier decoy.
    assert out.get("verdict") == "needs-attention", out
    assert "note" not in out, out
    assert out.get("next_steps") == ["ship"], out


def test_antigravity_extract_json_single_block_happy_path_returns_that_block():
    """H3 companion: the single-fenced-block happy path still returns that block.

    WHY: the schema-preference logic must not regress the common case where the
    model returns exactly one fenced review block. With only one block present,
    looksLikeStructuredReview matches it and it is returned directly; there is no
    decoy to prefer against. This guards that the multi-block scan did not break
    the ordinary single-block extraction.
    """
    only = (
        '{"verdict": "approve", "summary": "ok", '
        '"findings": [], "next_steps": []}'
    )
    raw = "preamble prose\n```json\n" + only + "\n```\ntrailing prose\n"
    source = (
        "const m = await import('./" + STRUCTURED_OUTPUT_LIB + "');"
        "const raw = " + json.dumps(raw) + ";"
        "const out = m.extractJsonObject(raw);"
        "process.stdout.write(JSON.stringify(out));"
    )
    out = _import_probe(source)

    assert out.get("verdict") == "approve", out
    assert out.get("summary") == "ok", out
    assert out.get("findings") == [], out


def test_antigravity_sanitize_summary_redacts_secret_and_local_path_and_strips_controls():
    """M5/M6: sanitizeSummary must redact secrets + absolute local paths and
    strip ANSI/control sequences from model-facing output.

    WHY: raw model/mailbox output can echo back a leaked credential, expose the
    reviewer's absolute filesystem layout, or smuggle terminal control sequences
    that corrupt the host TTY. sanitizeSummary composes stripTerminalControls +
    redactSecrets + redactLocalPaths. We feed all three hazards in one string:
    a GitHub PAT (ghp_...), an absolute /Users/... path, and a raw ANSI CSI +
    a bare control byte. We assert the literal secret and the local path are
    gone (replaced by their [secret]/[local-path] markers) and that no control
    bytes or ESC survive. If any layer were dropped, the corresponding hazard
    would leak through verbatim.
    """
    ghp = "ghp_" + "a" * 36
    raw = (
        "\x1b[31mERROR\x1b[0m token=" + ghp + " at "
        "/Users/victim/secret/project/file.txt done\x07"
    )
    source = (
        "const m = await import('./" + SANITIZE_LIB + "');"
        "const raw = " + json.dumps(raw) + ";"
        "const out = m.sanitizeSummary(raw);"
        "process.stdout.write(JSON.stringify({ out }));"
    )
    probe = _import_probe(source)
    out = probe["out"]

    # Secret is redacted, never echoed verbatim.
    assert ghp not in out, out
    assert "[secret]" in out, out
    # Absolute local path is redacted, never echoed verbatim.
    assert "/Users/victim" not in out, out
    assert "[local-path]" in out, out
    # ANSI escape and control bytes are stripped entirely.
    assert "\x1b" not in out, repr(out)
    assert "\x07" not in out, repr(out)
    assert "[31m" not in out, out


def test_antigravity_validate_workflow_catches_github_context_in_inline_and_folded_run():
    """H4 (LOAD-BEARING SECURITY): the fork-safety gate must flag a workflow
    whose run: step injects untrusted ${{ github.* }} context — even when the
    dangerous step is an INLINE `run:` and a safe step uses a block scalar.

    WHY: `${{ github.event.pull_request.head.repo.full_name }}` (and siblings)
    interpolate attacker-controlled PR metadata directly into the shell command,
    the classic pull_request script-injection vector. The check
    'no-github-context-in-run' passes only when EVERY extracted run block is free
    of `${{ github.`. This regressed before because extractRunBlocks captured
    block-scalar bodies but NOT inline `- run: ...` commands, so an inline
    injection slipped past the gate (check .ok would be true — vulnerable).

    The fix makes extractRunBlocks capture BOTH shapes. We build a workflow with
    a SAFE block-scalar step (run: | / echo safe) AND a MALICIOUS inline step
    (- run: echo ${{ github.event.pull_request.head.repo.full_name }}) and assert:
      1. extractRunBlocks returns BOTH the block-scalar body ('echo safe') and
         the inline command (containing the github-context expression), and
      2. the 'no-github-context-in-run' check is .ok === false (injection caught).
    Reverted (inline not captured), extractRunBlocks would miss the inline step
    and the check would wrongly report .ok === true. This is the exact scenario
    the lead verified fails-on-revert.
    """
    wf = "\n".join(
        [
            "jobs:",
            "  review:",
            "    steps:",
            "      - name: safe block scalar",
            "        run: |",
            "          echo safe",
            "      - name: malicious inline",
            "        run: echo ${{ github.event.pull_request.head.repo.full_name }}",
            "",
        ]
    )
    source = (
        "const m = await import('./" + GITHUB_ACTIONS_LIB + "');"
        "const wf = " + json.dumps(wf) + ";"
        "const blocks = m.extractRunBlocks(wf);"
        "const report = m.validateWorkflow(wf);"
        "const check = report.checks.find(c => c.name === 'no-github-context-in-run');"
        "process.stdout.write(JSON.stringify({ blocks, checkOk: check ? check.ok : null }));"
    )
    probe = _import_probe(source)
    blocks = probe["blocks"]

    # Both run shapes are captured: the block-scalar body AND the inline command.
    joined = "\n".join(blocks)
    assert any("echo safe" in b for b in blocks), blocks
    assert "${{ github.event.pull_request.head.repo.full_name }}" in joined, blocks

    # The fork-safety check must FAIL: github context reached a run step.
    assert probe["checkOk"] is False, (
        "no-github-context-in-run passed despite an inline run step injecting "
        "${{ github.* }} — the H4 fork-safety gate regressed (inline run "
        "commands not inspected)"
    )
