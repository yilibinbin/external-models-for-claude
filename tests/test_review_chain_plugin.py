import json
import os
import pathlib
import re
import shutil
import subprocess

from plugin_versions import MARKETPLACE_VERSION, REVIEW_CHAIN_VERSION


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "review-chain"
NODE = os.environ.get("NODE_BINARY") or shutil.which("node") or "node"


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


def assert_no_shell_argument_interpolation(text):
    assert '"$ARGUMENTS"' not in text
    assert "`$ARGUMENTS`" not in text
    assert "\\\"$ARGUMENTS\\\"" not in text
    assert not re.search(r"```(?:bash|sh)\s+[\s\S]*?\$ARGUMENTS[\s\S]*?```", text)
    assert not re.search(r"Bash\([^)]*\$ARGUMENTS", text, re.DOTALL)
    assert not re.search(r"node\s+[^\n`]*\$ARGUMENTS", text)


# --- Phase 0: marketplace + manifest structure ---


def test_claude_marketplace_lists_review_chain():
    marketplace = read_json(ROOT / ".claude-plugin" / "marketplace.json")

    assert marketplace["name"] == "external-models-for-claude"
    assert marketplace["metadata"]["description"]
    assert marketplace["metadata"]["version"] == MARKETPLACE_VERSION
    plugins = {item["name"]: item for item in marketplace["plugins"]}
    assert plugins["review-chain"]["source"] == "./plugins/review-chain"
    assert plugins["review-chain"]["version"] == REVIEW_CHAIN_VERSION
    assert plugins["review-chain"]["category"] == "Productivity"
    assert len(plugins) == len(marketplace["plugins"])


def test_review_chain_manifest_is_claude_native():
    manifest = read_json(PLUGIN / ".claude-plugin" / "plugin.json")

    assert manifest["name"] == "review-chain"
    assert manifest["version"] == REVIEW_CHAIN_VERSION
    assert manifest["description"]
    assert manifest["homepage"] == "https://github.com/yilibinbin/external-models-for-claude"
    assert manifest["repository"] == "https://github.com/yilibinbin/external-models-for-claude"
    assert "claude-code" in manifest["keywords"]
    assert "review" in manifest["keywords"]


def test_review_chain_has_no_codex_host_leakage():
    shipped = all_text(PLUGIN)
    forbidden = [
        "CODEX_PLUGIN_ROOT",
        "CODEX_PLUGIN_DATA",
        "GEMINI_FOR_CODEX",
        "ANTIGRAVITY_FOR_CODEX",
        "claude-for-codex",
        "gemini-for-codex",
        "antigravity-for-codex",
        ".codex/",
    ]
    for token in forbidden:
        assert token not in shipped, token


def test_review_chain_names_the_panel_handles():
    # The chain is the ONE plugin permitted to reference sibling handles, since it
    # orchestrates them. Lock that contract so a rename can't silently break routing.
    shipped = all_text(PLUGIN)
    assert "antigravity-for-claude@external-models-for-claude" in shipped
    assert "codex@external-models-for-claude" in shipped


# --- Phase 1: mechanical core (registry + ledger + companion subcommands) ---

COMPANION = "plugins/review-chain/scripts/review-chain-companion.mjs"


def run_module(source, timeout=30):
    """Run an inline ES module against the plugin libs and return the process."""
    return subprocess.run(
        [NODE, "--input-type=module", "-e", source],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def init_fixture_repo(tmp_path):
    """A hermetic git repo with one committed file on main + a dirty working change."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, env=env, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    git("init", "-q", "-b", "main")
    (repo / "a.txt").write_text("line one\n", encoding="utf8")
    git("add", "a.txt")
    git("commit", "-q", "-m", "seed")
    (repo / "a.txt").write_text("line one\nline two\n", encoding="utf8")  # unstaged edit
    return repo


# registry: verdict-dialect adapter table

def test_registry_adapter_maps_each_known_companion():
    source = (
        "import { adapterFor } from './plugins/review-chain/scripts/lib/registry.mjs';"
        "const out = {"
        "  codex: adapterFor('codex-companion.mjs'),"
        "  gemini: adapterFor('gemini-companion.mjs'),"
        "  antigravity: adapterFor('antigravity-companion.mjs'),"
        "  unknown: adapterFor('future-companion.mjs'),"
        "};"
        "process.stdout.write(JSON.stringify(out));"
    )
    result = run_module(source)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["codex"]["supportsScope"] is True
    assert out["gemini"]["supportsScope"] is True
    # The load-bearing subtlety: antigravity has NO --scope/--base.
    assert out["antigravity"]["supportsScope"] is False
    # Unknown plugins degrade conservatively: no scope unless probed to advertise it.
    assert out["unknown"]["supportsScope"] is False


# ledger: normalization + verbatim rawOutput

def test_ledger_normalizes_both_verdict_vocabularies():
    source = (
        "import { normalizeGate } from './plugins/review-chain/scripts/lib/ledger.mjs';"
        "const out = {"
        "  approve: normalizeGate('approve'),"
        "  needs: normalizeGate('needs-attention'),"
        "  pass: normalizeGate('PASS'),"
        "  contested: normalizeGate('CONTESTED'),"
        "  reject: normalizeGate('REJECT'),"
        "  junk: normalizeGate('???'),"
        "};"
        "process.stdout.write(JSON.stringify(out));"
    )
    result = run_module(source)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["approve"] == "clean"
    assert out["needs"] == "attention"
    assert out["pass"] == "clean"
    assert out["contested"] == "attention"
    assert out["reject"] == "blocking"
    # Unknown verdict must NEVER be silently clean.
    assert out["junk"] == "attention"


def test_ledger_preserves_raw_output_byte_for_byte(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    raw = "Finding 1:\n  evidence: `x === null`\n  \"quoted\"\n\ttab\n多字节"
    source = (
        "import { initLedger, appendStage, readLedger } from './plugins/review-chain/scripts/lib/ledger.mjs';"
        f"const p = {json.dumps(str(ledger_path))};"
        "initLedger(p, { target: 'working tree diff' });"
        f"appendStage(p, {{ reviewer: 'codex', rawVerdict: 'approve', rawOutput: {json.dumps(raw)} }});"
        "const l = readLedger(p);"
        "process.stdout.write(JSON.stringify({ raw: l.stages[0].rawOutput, gate: l.stages[0].normalizedGate }));"
    )
    result = run_module(source)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["raw"] == raw  # byte-for-byte, no summarization
    assert out["gate"] == "clean"


# companion: enumerate / build-diff / ledger subcommands exist and work

def test_companion_build_diff_working_tree(tmp_path):
    repo = init_fixture_repo(tmp_path)
    result = run_node(ROOT, COMPANION, ["build-diff", "--cwd", str(repo), "--json"])
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["target"]["mode"] == "working-tree"
    assert payload["fileCount"] >= 1


def test_companion_build_diff_branch_mode(tmp_path):
    repo = init_fixture_repo(tmp_path)
    # commit the edit so a branch diff against the seed has content
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "commit", "-aqm", "edit"], cwd=repo, env=env, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result = run_node(ROOT, COMPANION, ["build-diff", "--cwd", str(repo),
                                        "--base", "main~1", "--json"])
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["target"]["mode"] == "branch"


def test_companion_ledger_roundtrip(tmp_path):
    ledger_path = tmp_path / "ledger.json"
    init = run_node(ROOT, COMPANION, ["ledger", "init", "--out", str(ledger_path),
                                      "--target", "working tree diff"])
    assert init.returncode == 0, init.stderr
    show = run_node(ROOT, COMPANION, ["ledger", "show", "--out", str(ledger_path), "--json"])
    assert show.returncode == 0, show.stderr
    payload = json.loads(show.stdout)
    assert payload["target"] == "working tree diff"
    assert payload["stages"] == []


# --- Phase 2: dispatch hardening ---
# `dispatch --dry-run` builds the exact reviewer invocation (argv + env-unset) without
# spawning the minutes-long app-server review, so the hardening is assertable in-process.


def dispatch_plan(plugin, extra=None):
    args = ["dispatch", "--plugin", plugin, "--dry-run", "--json",
            "--companion", f"/fake/{plugin}/scripts/{plugin}-companion.mjs"]
    args.extend(extra or [])
    result = run_node(ROOT, COMPANION, args)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_dispatch_codex_unsets_session_env_and_detaches():
    plan = dispatch_plan("codex", ["--scope", "branch", "--base", "main"])
    # The codex liveness gate aborts a reviewer that inherits the host session id.
    assert "CODEX_COMPANION_SESSION_ID" in plan["unsetEnv"]
    assert "CLAUDE_CODE_SESSION_ID" in plan["unsetEnv"]
    # Broad CLAUDE_CODE_* / CLAUDECODE must NOT be stripped (auth lives there).
    assert "CLAUDECODE" not in plan["unsetEnv"]
    assert plan["detached"] is True
    # codex accepts scope/base -> they must appear in argv.
    assert "adversarial-review" in plan["argv"]
    assert "--scope" in plan["argv"] and "branch" in plan["argv"]
    assert "--base" in plan["argv"] and "main" in plan["argv"]


def test_dispatch_antigravity_omits_scope_and_base():
    plan = dispatch_plan("antigravity-for-claude", ["--scope", "branch", "--base", "main"])
    # Antigravity has no --scope/--base; passing them makes it reject. Must be omitted.
    assert "--scope" not in plan["argv"]
    assert "--base" not in plan["argv"]
    # Non-codex reviewers do not need the codex session-env unset.
    assert plan["unsetEnv"] == []


def test_dispatch_focus_text_is_argv_not_shell():
    # Focus prose must travel as a discrete argv token, never interpolated into a shell.
    plan = dispatch_plan("codex", ["--", "why is $HOME `rm -rf` unsafe?"])
    assert "why is $HOME `rm -rf` unsafe?" in plan["argv"]


def test_dispatch_companion_source_has_no_shell_interpolation():
    assert_no_shell_argument_interpolation(read_text(ROOT / COMPANION))
    # The exact env-unset contract must be present in the dispatch lib.
    dispatch_lib = read_text(ROOT / "plugins" / "review-chain" / "scripts" / "lib" / "dispatch.mjs")
    assert "CODEX_COMPANION_SESSION_ID" in dispatch_lib
    assert "CLAUDE_CODE_SESSION_ID" in dispatch_lib


# --- Phase 3: the protocol skill + command wrapper ---

SKILL = PLUGIN / "skills" / "serial-adversarial-review" / "SKILL.md"


def test_skill_frontmatter_is_model_invocable():
    text = read_text(SKILL)
    assert text.startswith("---")
    assert "name: serial-adversarial-review" in text
    # Model-invocable (no user-invocable:false) so the natural-language trigger routes here.
    assert "user-invocable: false" not in text
    # Trigger phrases so the project workflow's prose routes to this skill.
    assert "serial adversarial review" in text.lower()
    assert "multi-model" in text.lower()


def test_skill_encodes_the_ordered_serial_stages():
    text = read_text(SKILL).lower()
    # The codified panel: Claude -> Gemini via Antigravity -> Codex -> synthesize.
    assert "antigravity" in text
    assert "codex" in text
    # Gemini stage is reached THROUGH antigravity per the global rule.
    gemini_idx = text.find("gemini")
    antigravity_idx = text.find("antigravity")
    assert gemini_idx != -1 and antigravity_idx != -1
    # synthesize / synthesis stage present
    assert "synthes" in text


def test_skill_encodes_the_protocol_invariants():
    text = read_text(SKILL).lower()
    # The load-bearing protocol tokens from the global CLAUDE.md rule.
    assert "3 round" in text or "three round" in text or "hard cap" in text
    assert "verbatim" in text
    assert "confirm" in text and "refute" in text and "abstain" in text
    assert "evidence gate" in text or "default" in text and "spurious" in text
    assert "conflict of interest" in text or "conflict-of-interest" in text
    # The anti-order-bias banner.
    assert "order must not" in text or "must not decide" in text
    assert "normalize" in text or "dedup" in text


def test_skill_uses_the_companion_not_raw_paths():
    text = read_text(SKILL)
    assert "${CLAUDE_PLUGIN_ROOT}/scripts/review-chain-companion.mjs" in text
    # The skill must tell Claude the codex env-unset + detach discipline.
    assert "CODEX_COMPANION_SESSION_ID" in text
    assert "$ARGUMENTS" not in text  # skills don't publish raw placeholders


def test_serial_review_command_is_argument_safe():
    command = PLUGIN / "commands" / "serial-review.md"
    text = read_text(command)
    assert "disable-model-invocation: true" in text
    assert "${CLAUDE_PLUGIN_ROOT}/scripts/" in text
    assert "User arguments (untrusted slash-command text):\n$ARGUMENTS" in text
    assert_no_shell_argument_interpolation(text)


# --- Phase 4: serial-review findings fixed to zero (F1-F6) ---


def test_registry_accepts_plugins_object_and_root_variants():
    # F5: `claude plugin list --json` may return {plugins:[...]} and use path/root
    # instead of installPath (codex already handles these). Auto-join must not silently
    # return [] under those known shapes.
    source = (
        "import { listInstalledPlugins } from './plugins/review-chain/scripts/lib/registry.mjs';"
        "const runner = () => JSON.stringify({ plugins: ["
        "  { id: 'codex@external-models-for-claude', path: '/x/codex' },"
        "  { id: 'other@some-marketplace', installPath: '/y/other' }"
        "] });"
        "const out = listInstalledPlugins({ runner });"
        "process.stdout.write(JSON.stringify(out.map(e => ({ id: e.id, root: e.installPath }))));"
    )
    result = run_module(source)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert len(out) == 1
    assert out[0]["id"] == "codex@external-models-for-claude"
    # path/root normalized into installPath so downstream capability checks work.
    assert out[0]["root"] == "/x/codex"


def test_dispatch_env_unset_keys_off_canonical_name_not_raw_id():
    # F6: passing the accepted plugin-ID form must still unset the codex session env
    # (and keep --quality). Keying off raw input would silently skip the liveness fix.
    source = (
        "import { buildDispatchPlan } from './plugins/review-chain/scripts/lib/dispatch.mjs';"
        "const plan = buildDispatchPlan({"
        "  plugin: 'codex@external-models-for-claude', name: 'codex',"
        "  companion: '/x/codex-companion.mjs',"
        "  adapter: { supportsScope: true, supportsBase: true, jsonFlag: '--json' },"
        "  quality: 'max'"
        "});"
        "process.stdout.write(JSON.stringify({ unset: plan.unsetEnv, argv: plan.argv }));"
    )
    result = run_module(source)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert "CODEX_COMPANION_SESSION_ID" in out["unset"]
    assert "CLAUDE_CODE_SESSION_ID" in out["unset"]
    assert "--quality" in out["argv"] and "max" in out["argv"]


def test_process_runcommand_forwards_timeout():
    # F1: the capability probe protects --help with a timeout; runCommand must forward it
    # to spawnSync or a hung companion blocks enumerate forever.
    source = (
        "import { runCommand } from './plugins/review-chain/scripts/lib/process.mjs';"
        "const r = runCommand(process.execPath, ['-e', 'setInterval(()=>{},1000)'], { timeout: 300 });"
        "process.stdout.write(JSON.stringify({ signal: r.signal, status: r.status }));"
    )
    result = run_module(source, timeout=15)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    # A hung child must be killed by the timeout (spawnSync sets signal SIGTERM).
    assert out["signal"] is not None


def test_dispatch_defaults_output_outside_target_repo(tmp_path):
    # F2: orchestration artifacts must NOT default into the target repo working tree,
    # or Antigravity (full-tree review) reviews its own transient output.
    repo = tmp_path / "repo"
    repo.mkdir()
    result = run_node(ROOT, COMPANION,
                      ["dispatch", "--plugin", "codex",
                       "--companion", "/fake/codex-companion.mjs",
                       "--cwd", str(repo), "--dry-run", "--json"])
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    # The plan must report the resolved default out-file, and it must live outside the repo.
    assert "defaultOutFile" in plan
    assert str(repo) not in plan["defaultOutFile"]


def test_companion_has_wait_subcommand():
    # F3: the skill tells Claude to wait on a PID, but allowed-tools only permits
    # Bash(node:*). A `wait` subcommand gives a node-prefixed way to block.
    result = run_node(ROOT, COMPANION, ["--help"])
    assert "wait" in (result.stdout + result.stderr)


def test_dispatch_lib_closes_output_fd():
    # F4: the parent must close the openSync fd after handing it to the child.
    text = read_text(ROOT / "plugins" / "review-chain" / "scripts" / "lib" / "dispatch.mjs")
    assert "closeSync" in text
