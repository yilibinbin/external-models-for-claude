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
    assert {"gemini-for-claude", "antigravity-for-claude"} <= set(plugins)
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
