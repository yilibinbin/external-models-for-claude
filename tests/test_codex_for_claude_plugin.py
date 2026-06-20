import json
import os
import pathlib
import re
import shutil
import subprocess

from plugin_versions import CODEX_VERSION as FALLBACK_CODEX_VERSION
from plugin_versions import MARKETPLACE_VERSION as FALLBACK_MARKETPLACE_VERSION


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex"
NODE = os.environ.get("NODE_BINARY") or shutil.which("node") or "node"
RELEASE_CHECK_MODULE = PLUGIN / "scripts" / "lib" / "release-check.mjs"

FALLBACK_MARKETPLACE_CODEX_AUTHOR = {
    "name": "OpenAI",
    "url": "https://github.com/openai/codex-plugin-cc",
}
FALLBACK_PLUGIN_CODEX_AUTHOR = {"name": "OpenAI"}
FALLBACK_EXPECTED_COMMANDS = [
    "adversarial-review.md",
    "cancel.md",
    "doctor.md",
    "rescue.md",
    "result.md",
    "review.md",
    "setup.md",
    "status.md",
]


def read_json(path):
    return json.loads(path.read_text(encoding="utf8"))


def read_text(path):
    return path.read_text(encoding="utf8")


def load_release_check_exports():
    if not RELEASE_CHECK_MODULE.exists():
        return {}
    script = """
        import * as mod from './plugins/codex/scripts/lib/release-check.mjs';
        const keys = [
          'MARKETPLACE_VERSION',
          'CODEX_VERSION',
          'MARKETPLACE_CODEX_AUTHOR',
          'PLUGIN_CODEX_AUTHOR',
          'EXPECTED_COMMANDS',
          'PREVIEW_COMMANDS',
          'READY_COMMANDS'
        ];
        const output = {};
        for (const key of keys) {
          const value = mod[key];
          output[key] = value instanceof Set ? Array.from(value) : value;
        }
        console.log(JSON.stringify(output));
    """
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def load_machine_path_pattern():
    script = (
        "import { MACHINE_PATH_PATTERN_SOURCE } "
        "from './plugins/codex/scripts/lib/path-hygiene.mjs';"
        "console.log(MACHINE_PATH_PATTERN_SOURCE);"
    )
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return re.compile(result.stdout.strip(), re.MULTILINE)


RELEASE_CHECK_EXPORTS = load_release_check_exports()
MARKETPLACE_VERSION = RELEASE_CHECK_EXPORTS.get("MARKETPLACE_VERSION", FALLBACK_MARKETPLACE_VERSION)
CODEX_VERSION = RELEASE_CHECK_EXPORTS.get("CODEX_VERSION", FALLBACK_CODEX_VERSION)
MARKETPLACE_CODEX_AUTHOR = RELEASE_CHECK_EXPORTS.get(
    "MARKETPLACE_CODEX_AUTHOR", FALLBACK_MARKETPLACE_CODEX_AUTHOR
)
PLUGIN_CODEX_AUTHOR = RELEASE_CHECK_EXPORTS.get("PLUGIN_CODEX_AUTHOR", FALLBACK_PLUGIN_CODEX_AUTHOR)
EXPECTED_COMMANDS = RELEASE_CHECK_EXPORTS.get("EXPECTED_COMMANDS", FALLBACK_EXPECTED_COMMANDS)
READY_COMMANDS = RELEASE_CHECK_EXPORTS.get("READY_COMMANDS", EXPECTED_COMMANDS)
MACHINE_PATH_PATTERN = load_machine_path_pattern()


def should_expect_marketplace_entry_version(root=ROOT):
    script = """
        import { shouldExpectMarketplaceEntryVersion } from './plugins/codex/scripts/lib/release-check.mjs';
        console.log(JSON.stringify(shouldExpectMarketplaceEntryVersion(process.argv[1])));
    """
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script, str(root)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def assert_no_machine_paths(text):
    assert not MACHINE_PATH_PATTERN.search(text)


def run_release_check(root=ROOT, args=None):
    command_args = ["--json"] if args is None else args
    return subprocess.run(
        [NODE, "plugins/codex/scripts/codex-companion.mjs", "release-check", *command_args],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def run_companion(args, cwd=ROOT, env=None):
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    return subprocess.run(
        [NODE, str(PLUGIN / "scripts" / "codex-companion.mjs"), *args],
        cwd=cwd,
        env=command_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def write_executable(path, text):
    path.write_text(text, encoding="utf8")
    path.chmod(0o755)


def fake_cli_dir(tmp_path, claude_plugin_list):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_executable(
        bin_dir / "codex",
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then\n"
        "  printf 'codex 1.0.0\\n'\n"
        "  exit 0\n"
        "fi\n"
        "printf 'fake codex\\n'\n",
    )
    write_executable(
        bin_dir / "claude",
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then\n"
        "  printf 'claude 1.0.0\\n'\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"plugin\" ] && [ \"$2\" = \"list\" ] && [ \"$3\" = \"--json\" ]; then\n"
        f"  printf '%s\\n' '{json.dumps(claude_plugin_list)}'\n"
        "  exit 0\n"
        "fi\n"
        "printf 'unexpected fake claude args: %s\\n' \"$*\" >&2\n"
        "exit 1\n",
    )
    return bin_dir


def companion_env(tmp_path, bin_dir):
    return {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin-data"),
    }


def fenced_bash_blocks(text):
    return re.findall(r"```bash\n(.*?)```", text, re.DOTALL)


def js_function_body(source, name):
    match = re.search(rf"(?:async\s+)?function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", source)
    assert match, name
    index = match.end()
    depth = 1
    while index < len(source) and depth:
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    assert depth == 0, name
    return source[match.end(): index - 1]


def release_check_payload(result):
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def checks_by_name(payload):
    return {check["name"]: check for check in payload["checks"]}


def copy_repo(tmp_path):
    destination = tmp_path / "repo"
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__", "node_modules"),
    )
    return destination


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf8")


def run_node_script(script, cwd=ROOT, env=None, args=None):
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script, *(args or [])],
        cwd=cwd,
        env=command_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout or "{}")


def test_codex_plugin_is_local_fork_with_openai_attribution():
    marketplace = read_json(ROOT / ".claude-plugin" / "marketplace.json")
    manifest = read_json(PLUGIN / ".claude-plugin" / "plugin.json")
    plugin_entry = {item["name"]: item for item in marketplace["plugins"]}["codex"]

    assert marketplace["metadata"]["version"] == MARKETPLACE_VERSION
    expect_marketplace_entry_version = should_expect_marketplace_entry_version()
    if expect_marketplace_entry_version:
        assert plugin_entry["version"] == CODEX_VERSION
    else:
        assert "version" not in plugin_entry
    assert manifest["version"] == CODEX_VERSION
    assert plugin_entry["author"] == MARKETPLACE_CODEX_AUTHOR
    assert manifest["author"] == PLUGIN_CODEX_AUTHOR
    assert "url" in plugin_entry["author"]
    assert "url" not in manifest["author"]
    assert "OpenAI" in manifest["author"]["name"]
    assert "extensions by fanghao" in manifest["description"]
    assert (PLUGIN / "LICENSE").exists()
    assert (PLUGIN / "NOTICE").exists()
    assert (PLUGIN / "FORK_NOTICE.md").exists()
    assert (PLUGIN / "AUTHOR_ATTRIBUTION_CONFIRMATION.md").exists()
    assert (PLUGIN / "VERSION_AXIS_CONFIRMATION.md").exists()
    fork_notice = read_text(PLUGIN / "FORK_NOTICE.md")
    assert "OpenAI-authored" in fork_notice
    assert "Apache-2.0" in fork_notice
    assert "unverified upstream lineage" in fork_notice
    confirmation = read_text(PLUGIN / "AUTHOR_ATTRIBUTION_CONFIRMATION.md")
    assert "confirmed" in confirmation.lower()
    assert "OpenAI" in confirmation
    version_evidence = read_text(PLUGIN / "VERSION_AXIS_CONFIRMATION.md")
    assert "validatorUnavailable: true" in version_evidence or "claude plugin validate --strict" in version_evidence
    assert "validatorUnavailable: false" in version_evidence or "validatorUnavailable: true" in version_evidence
    assert CODEX_VERSION in version_evidence or "0.2.0 fallback" in version_evidence or "fallback B" in version_evidence
    assert "claude plugin list --json" in version_evidence
    assert "codex@external-models-for-claude" in version_evidence
    assert "not installed" in version_evidence.lower()
    assert "unverified/skipped" in version_evidence.lower()
    assert_no_machine_paths(version_evidence)
    if "validatorUnavailable: true" in version_evidence:
        assert "release blocked" in version_evidence.lower()


def test_codex_docs_have_install_and_fork_notice_without_machine_paths():
    install_docs = [
        ROOT / "README.md",
        ROOT / "docs" / "README.en.md",
        ROOT / "docs" / "README.zh-CN.md",
        PLUGIN / "README.md",
    ]
    governance_docs = [
        ROOT / "THIRD_PARTY_NOTICES.md",
        PLUGIN / "FORK_NOTICE.md",
        PLUGIN / "AUTHOR_ATTRIBUTION_CONFIRMATION.md",
        PLUGIN / "VERSION_AXIS_CONFIRMATION.md",
        PLUGIN / "CHANGELOG.md",
    ]
    for doc in [*install_docs, *governance_docs]:
        assert doc.exists(), doc
        assert_no_machine_paths(read_text(doc))

    for doc in install_docs:
        text = read_text(doc)
        assert "claude plugin marketplace add yilibinbin/external-models-for-claude --scope user" in text
        assert "codex@external-models-for-claude" in text
        assert "OpenAI" in text
    notices = read_text(ROOT / "THIRD_PARTY_NOTICES.md")
    assert "OpenAI" in notices
    assert "Apache" in notices
    assert "Version included: 1.0.4" in notices
    assert "Local extended version: 1.1.0-fh.1" in notices
    root_license = read_text(ROOT / "LICENSE")
    assert root_license.splitlines()[0] == "MIT License"


def test_codex_readme_documents_default_model_call_saturation_caveat():
    text = read_text(PLUGIN / "README.md")
    assert "default global `model-call` limit is 2" in text
    assert "two concurrent model-call commands" in text
    assert "one `multi-review` plus one long task" in text
    assert "saturate the pool" in text
    assert "next foreground review or task return `capacity_blocked`" in text
    assert "Stop-gate review uses the independent `stop-gate` pool" in text
    assert "always-available spare slot" not in text.lower()


def test_codex_commands_do_not_disable_model_invocation():
    for command_path in sorted((PLUGIN / "commands").glob("*.md")):
        text = read_text(command_path)
        assert "disable-model-invocation" not in text, command_path.name


def test_machine_path_pattern_catches_common_local_path_shapes():
    positives = [
        "/Users/fanghao/Documents/Claude for codex",
        "`/Users/fanghao/private`",
        "`file:///Users/fanghao/private`",
        "[/Users/fanghao/private](https://example.com)",
        "[file:///Users/fanghao/private](https://example.com)",
        "file:///Users/fanghao/private",
        "<file:///Users/fanghao/private>",
        "|/Users/fanghao/private|",
        ",/Users/fanghao/private",
        "{/Users/fanghao/private}",
        "/home/alice/project",
        "file:///home/alice/project",
        "/private/var/folders/p6/mbyd_p7d1md2wcqhq2g07tw00000gn/T/repo",
        "file:///private/var/folders/p6/mbyd_p7d1md2wcqhq2g07tw00000gn/T/repo",
        "<file:///private/var/folders/p6/mbyd_p7d1md2wcqhq2g07tw00000gn/T/repo>",
        "/var/folders/p6/mbyd_p7d1md2wcqhq2g07tw00000gn/T/repo",
        "file:///var/folders/p6/mbyd_p7d1md2wcqhq2g07tw00000gn/T/repo",
        "file:///Volumes/Workspace/project",
        "<file:///Volumes/Workspace/project>",
        "/Volumes/Macintosh HD/project",
        "`/Volumes/Macintosh HD/project`",
        "file:///Volumes/Macintosh%20HD/project",
        "`file:///Volumes/Macintosh%20HD/project`",
        "[file:///Volumes/Macintosh%20HD/project](https://example.com)",
        "<file:///Volumes/Macintosh%20HD/project>",
        r"C:\Users\Jane Doe\AppData\Local\Temp\repo",
        "C:/Users/Jane Doe/AppData/Local/Temp/repo",
        "file:///C:/Users/Jane%20Doe/AppData/Local/Temp/repo",
        "<file:///C:/Users/Jane%20Doe/AppData/Local/Temp/repo>",
    ]
    negatives = [
        "/home/runner/work/external-models-for-claude",
        "file:///home/runner/work/external-models-for-claude",
        "/home/vscode/workspace",
        "/home/ubuntu/project",
        "/home/circleci/project",
        "/home/runneradmin/project",
        "/Volumes/<Disk>/project",
        "/Volumes/${VOLUME}/project",
        "C:/Users/<username>/project",
        "file:///C:/Users/<username>/project",
        r"\\server\share\project",
        "file://server/share/project",
    ]
    for text in positives:
        assert MACHINE_PATH_PATTERN.search(text), text
    for text in negatives:
        assert not MACHINE_PATH_PATTERN.search(text), text


def test_codex_release_check_passes():
    payload = release_check_payload(run_release_check())
    checks = checks_by_name(payload)

    assert payload["ok"] is True
    for name in [
        "manifest-version",
        "marketplace-codex-entry",
        "fork-notice",
        "hooks-shape",
        "command-surface",
        "docs-install",
        "no-machine-paths",
    ]:
        assert checks[name]["ok"] is True

    assert {"SessionStart", "SessionEnd", "Stop"}.issubset(set(checks["hooks-shape"]["detail"]))
    assert checks["command-surface"]["detail"] == EXPECTED_COMMANDS
    assert checks["ready-command-surface"]["detail"] == READY_COMMANDS


def test_codex_release_check_rejects_duplicate_marketplace_codex_entries(tmp_path):
    repo = copy_repo(tmp_path)
    marketplace_path = repo / ".claude-plugin" / "marketplace.json"
    marketplace = read_json(marketplace_path)
    duplicate = dict(marketplace["plugins"][0])
    duplicate["source"] = "./plugins/not-codex"
    duplicate["version"] = "9.9.9"
    marketplace["plugins"].append(duplicate)
    write_json(marketplace_path, marketplace)

    result = run_release_check(repo)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    assert payload["ok"] is False
    assert checks["marketplace-codex-entry"]["ok"] is False
    assert checks["marketplace-codex-entry"]["detail"]["matchingEntries"] == 2
    assert checks["marketplace-codex-author"]["ok"] is False


def test_codex_release_check_rejects_machine_paths(tmp_path):
    repo = copy_repo(tmp_path)
    readme = repo / "README.md"
    readme.write_text(f"{read_text(readme)}\nLocal-only path: /Users/fanghao/private\n", encoding="utf8")

    result = run_release_check(repo)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    assert payload["ok"] is False
    assert checks["no-machine-paths"]["ok"] is False
    assert "README.md" in json.dumps(checks["no-machine-paths"]["detail"])


def test_codex_release_check_rejects_inline_code_machine_paths_in_shipped_docs(tmp_path):
    repo = copy_repo(tmp_path)
    readme = repo / "plugins" / "codex" / "README.md"
    readme.write_text(f"{read_text(readme)}\nLocal-only inline code: `/Users/fanghao/private`\n", encoding="utf8")

    result = run_release_check(repo)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    detail = json.dumps(checks["no-machine-paths"]["detail"])
    assert checks["no-machine-paths"]["ok"] is False
    assert "plugins/codex/README.md" in detail


def test_codex_release_check_rejects_link_and_autolink_machine_paths_in_shipped_docs(tmp_path):
    repo = copy_repo(tmp_path)
    readme = repo / "plugins" / "codex" / "README.md"
    readme.write_text(
        f"{read_text(readme)}\n"
        "Local-only link text: [/Users/fanghao/private](https://example.com)\n"
        "Local-only URL: <file:///Users/fanghao/private>\n"
        "Local-only volume path: `/Volumes/Macintosh HD/project`\n"
        "Local-only volume URL: <file:///Volumes/Macintosh%20HD/project>\n",
        encoding="utf8",
    )

    result = run_release_check(repo)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    detail = json.dumps(checks["no-machine-paths"]["detail"])
    assert checks["no-machine-paths"]["ok"] is False
    assert "plugins/codex/README.md" in detail


def test_codex_release_check_scans_marketplace_metadata_for_machine_paths(tmp_path):
    repo = copy_repo(tmp_path)
    marketplace_path = repo / ".claude-plugin" / "marketplace.json"
    marketplace = read_json(marketplace_path)
    marketplace["metadata"]["description"] = (
        f"{marketplace['metadata']['description']} /Users/fanghao/private"
    )
    write_json(marketplace_path, marketplace)
    for ignored in ["task_plan.md", "findings.md", "progress.md"]:
        (repo / ignored).write_text("Local-only path: /Users/fanghao/private\n", encoding="utf8")
    superpowers_doc = repo / "docs" / "superpowers" / "note.md"
    superpowers_doc.parent.mkdir(parents=True, exist_ok=True)
    superpowers_doc.write_text("Local-only path: /Users/fanghao/private\n", encoding="utf8")

    result = run_release_check(repo)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    detail = json.dumps(checks["no-machine-paths"]["detail"])
    assert checks["no-machine-paths"]["ok"] is False
    assert ".claude-plugin/marketplace.json" in detail
    assert "task_plan.md" not in detail
    assert "findings.md" not in detail
    assert "progress.md" not in detail
    assert "docs/superpowers/note.md" not in detail


def test_codex_release_check_scans_shipped_mjs_scripts_for_template_literal_machine_paths(tmp_path):
    repo = copy_repo(tmp_path)
    script = repo / "plugins" / "codex" / "scripts" / "codex-companion.mjs"
    script.write_text(
        f"{read_text(script)}\nconst localPathFixtureForReleaseCheck = `/Users/fanghao/private`;\n",
        encoding="utf8",
    )

    result = run_release_check(repo)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    detail = json.dumps(checks["no-machine-paths"]["detail"])
    assert checks["no-machine-paths"]["ok"] is False
    assert "plugins/codex/scripts/codex-companion.mjs" in detail


def test_codex_release_check_scans_shipped_typescript_declarations_for_machine_paths(tmp_path):
    repo = copy_repo(tmp_path)
    declaration = repo / "plugins" / "codex" / "scripts" / "lib" / "app-server-protocol.d.ts"
    declaration.write_text(f"{read_text(declaration)}\n// Local-only path: /Users/fanghao/private\n", encoding="utf8")

    result = run_release_check(repo)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    detail = json.dumps(checks["no-machine-paths"]["detail"])
    assert checks["no-machine-paths"]["ok"] is False
    assert "plugins/codex/scripts/lib/app-server-protocol.d.ts" in detail


def test_codex_release_check_skips_symlinked_text_surfaces(tmp_path):
    repo = copy_repo(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("Local-only path: /Users/fanghao/private\n", encoding="utf8")
    os.symlink(outside, repo / "plugins" / "codex" / "symlinked.md")

    payload = release_check_payload(run_release_check(repo))
    checks = checks_by_name(payload)
    assert payload["ok"] is True
    assert checks["no-machine-paths"]["ok"] is True


def test_codex_release_check_skips_hidden_cache_dirs_but_scans_plugin_manifest(tmp_path):
    repo = copy_repo(tmp_path)
    hidden_cache = repo / "plugins" / "codex" / ".tmp-cache"
    hidden_cache.mkdir()
    (hidden_cache / "note.md").write_text("Local-only path: /Users/fanghao/private\n", encoding="utf8")

    payload = release_check_payload(run_release_check(repo))
    checks = checks_by_name(payload)
    assert payload["ok"] is True
    assert checks["no-machine-paths"]["ok"] is True

    manifest_path = repo / "plugins" / "codex" / ".claude-plugin" / "plugin.json"
    manifest = read_json(manifest_path)
    manifest["description"] = f"{manifest['description']} /Users/fanghao/private"
    write_json(manifest_path, manifest)

    result = run_release_check(repo)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    detail = json.dumps(checks["no-machine-paths"]["detail"])
    assert checks["no-machine-paths"]["ok"] is False
    assert "plugins/codex/.claude-plugin/plugin.json" in detail
    assert "plugins/codex/.tmp-cache/note.md" not in detail


def test_codex_release_check_scans_all_shipped_plugin_text_surfaces(tmp_path):
    repo = copy_repo(tmp_path)
    injected_files = [
        "plugins/codex/agents/codex-rescue.md",
        "plugins/codex/.claude-plugin/plugin.json",
        "plugins/codex/hooks/hooks.json",
        "plugins/codex/schemas/review-output.schema.json",
    ]

    agent = repo / injected_files[0]
    agent.write_text(f"{read_text(agent)}\nLocal-only path: /Users/fanghao/private\n", encoding="utf8")

    manifest = read_json(repo / injected_files[1])
    manifest["description"] = f"{manifest['description']} /Users/fanghao/private"
    write_json(repo / injected_files[1], manifest)

    hooks = read_json(repo / injected_files[2])
    hooks["description"] = f"{hooks['description']} /Users/fanghao/private"
    write_json(repo / injected_files[2], hooks)

    schema = read_json(repo / injected_files[3])
    schema["description"] = "/Users/fanghao/private"
    write_json(repo / injected_files[3], schema)

    result = run_release_check(repo)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    detail = json.dumps(checks["no-machine-paths"]["detail"])
    assert checks["no-machine-paths"]["ok"] is False
    for injected_file in injected_files:
        assert injected_file in detail


def test_codex_release_check_rejects_empty_required_hook_arrays(tmp_path):
    repo = copy_repo(tmp_path)
    hooks_path = repo / "plugins" / "codex" / "hooks" / "hooks.json"
    hooks = read_json(hooks_path)
    hooks["hooks"]["SessionStart"] = []
    write_json(hooks_path, hooks)

    result = run_release_check(repo)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    assert checks["hooks-shape"]["ok"] is False


def test_codex_release_check_rejects_extra_top_level_hook_events(tmp_path):
    repo = copy_repo(tmp_path)
    hooks_path = repo / "plugins" / "codex" / "hooks" / "hooks.json"
    hooks = read_json(hooks_path)
    hooks["hooks"]["PreToolUse"] = [
        {
            "hooks": [
                {
                    "type": "command",
                    "command": 'node "${CLAUDE_PLUGIN_ROOT}/scripts/unexpected-pre-tool-use.mjs"',
                    "timeout": 5,
                }
            ]
        }
    ]
    write_json(hooks_path, hooks)

    result = run_release_check(repo)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    detail = json.dumps(checks["hooks-shape"]["detail"])
    assert checks["hooks-shape"]["ok"] is False
    assert "PreToolUse" in detail


def test_codex_release_check_rejects_wrong_hook_commands_and_timeouts(tmp_path):
    repo = copy_repo(tmp_path)
    hooks_path = repo / "plugins" / "codex" / "hooks" / "hooks.json"
    hooks = read_json(hooks_path)
    hooks["hooks"]["Stop"][0]["hooks"][0]["command"] = "node wrong-stop-hook.mjs"
    hooks["hooks"]["SessionEnd"][0]["hooks"][0]["timeout"] = 0
    write_json(hooks_path, hooks)

    result = run_release_check(repo)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    assert checks["hooks-shape"]["ok"] is False


def test_codex_release_check_rejects_duplicate_expected_hook_commands(tmp_path):
    repo = copy_repo(tmp_path)
    hooks_path = repo / "plugins" / "codex" / "hooks" / "hooks.json"
    hooks = read_json(hooks_path)
    hooks["hooks"]["Stop"][0]["hooks"].append(dict(hooks["hooks"]["Stop"][0]["hooks"][0]))
    write_json(hooks_path, hooks)

    result = run_release_check(repo)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    detail = json.dumps(checks["hooks-shape"]["detail"])
    assert checks["hooks-shape"]["ok"] is False
    assert "Stop" in detail


def test_codex_release_check_rejects_unexpected_extra_hook_commands(tmp_path):
    repo = copy_repo(tmp_path)
    hooks_path = repo / "plugins" / "codex" / "hooks" / "hooks.json"
    hooks = read_json(hooks_path)
    hooks["hooks"]["Stop"][0]["hooks"].append(
        {
            "type": "command",
            "command": 'node "${CLAUDE_PLUGIN_ROOT}/scripts/unexpected-stop-hook.mjs"',
            "timeout": 900,
        }
    )
    write_json(hooks_path, hooks)

    result = run_release_check(repo)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    assert checks["hooks-shape"]["ok"] is False
    assert "unexpected-stop-hook.mjs" in json.dumps(checks["hooks-shape"]["detail"])


def test_codex_release_check_rejects_unknown_flags_and_positionals():
    unknown = run_release_check(args=["--bogus", "--json"])
    assert unknown.returncode != 0
    assert "Unsupported option --bogus" in unknown.stderr
    assert unknown.stdout == ""

    positional = run_release_check(args=["unexpected-positional", "--json"])
    assert positional.returncode != 0
    assert "Unexpected release-check argument" in positional.stderr
    assert positional.stdout == ""


def test_codex_doctor_json_reports_local_diagnostics(tmp_path):
    bin_dir = fake_cli_dir(tmp_path, {"plugins": []})
    result = run_companion(
        ["doctor", "--json"],
        cwd=tmp_path,
        env=companion_env(tmp_path, bin_dir),
    )
    assert result.returncode == 0, result.stderr
    assert str(tmp_path) not in result.stdout

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert isinstance(payload["ready"], bool)
    assert payload["checks"]["node"]["ok"] is True
    assert payload["checks"]["codexExecutable"]["ok"] is True
    assert payload["checks"]["claudeExecutable"]["ok"] is True
    assert payload["checks"]["installedPlugin"]["ok"] is False
    assert payload["stateDir"]["available"] is True
    assert payload["stateDir"]["writable"] is True
    assert "basename" in payload["stateDir"]
    assert "path" not in payload["stateDir"]

    doctor_source = read_text(PLUGIN / "scripts" / "lib" / "doctor.mjs")
    assert "ensureStateDir(cwd)" in doctor_source
    assert "writeFileSync" in doctor_source
    assert "probe" in doctor_source
    assert "unlinkSync" in doctor_source


def test_codex_doctor_omits_failed_command_output_from_json(tmp_path):
    bin_dir = fake_cli_dir(tmp_path, {"plugins": []})
    leaked_path = tmp_path / "private" / "codex-error.log"
    write_executable(
        bin_dir / "codex",
        "#!/bin/sh\n"
        "if [ \"$1\" = \"--version\" ]; then\n"
        f"  printf 'failed near {leaked_path}\\n'\n"
        f"  printf 'debug file: {leaked_path}\\n' >&2\n"
        "  exit 7\n"
        "fi\n"
        "exit 1\n",
    )

    result = run_companion(
        ["doctor", "--json"],
        cwd=tmp_path,
        env=companion_env(tmp_path, bin_dir),
    )
    assert result.returncode == 0, result.stderr
    assert str(leaked_path) not in result.stdout
    assert str(tmp_path) not in result.stdout

    payload = json.loads(result.stdout)
    codex_check = payload["checks"]["codexExecutable"]
    assert codex_check["ok"] is False
    assert codex_check["reason"] == "exit 7"
    assert "version" not in codex_check


def test_codex_doctor_redacts_installed_plugin_path(tmp_path):
    install_root = tmp_path / "installed" / "codex"
    (install_root / "scripts").mkdir(parents=True)
    (install_root / "scripts" / "codex-companion.mjs").write_text("", encoding="utf8")
    bin_dir = fake_cli_dir(
        tmp_path,
        {"plugins": [{"name": "codex", "installPath": str(install_root)}]},
    )

    result = run_companion(
        ["doctor", "--json"],
        cwd=tmp_path,
        env=companion_env(tmp_path, bin_dir),
    )
    assert result.returncode == 0, result.stderr
    assert str(install_root) not in result.stdout
    assert str(tmp_path) not in result.stdout

    payload = json.loads(result.stdout)
    installed = payload["checks"]["installedPlugin"]
    assert installed["ok"] is True
    assert installed["basename"] == "codex"
    assert "installPath" not in installed


def test_codex_doctor_treats_malformed_installed_plugin_root_as_advisory(tmp_path):
    bin_dir = fake_cli_dir(
        tmp_path,
        {"plugins": [{"name": "codex", "installPath": {}}]},
    )

    result = run_companion(
        ["doctor", "--json"],
        cwd=tmp_path,
        env=companion_env(tmp_path, bin_dir),
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""

    payload = json.loads(result.stdout)
    installed = payload["checks"]["installedPlugin"]
    assert installed["ok"] is False
    assert installed["advisory"] is True
    assert installed["reason"] == "installed codex plugin entry has no supported root field"
    assert payload["advisoryFailures"] == ["installedPlugin"]


def test_codex_doctor_command_exists_and_is_argument_safe():
    command_path = PLUGIN / "commands" / "doctor.md"
    text = read_text(command_path)

    assert "disable-model-invocation" not in text
    assert "allowed-tools: Bash(node:*)" in text
    assert '${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs' in text
    assert "$ARGUMENTS" in text
    for block in fenced_bash_blocks(text):
        assert "$ARGUMENTS" not in block


def test_codex_new_commands_reject_unsupported_flags(tmp_path):
    bin_dir = fake_cli_dir(tmp_path, {"plugins": []})
    env = companion_env(tmp_path, bin_dir)
    cases = [
        (["doctor", "--bad"], tmp_path),
        (["release-check", "--bad"], ROOT),
        (["setup", "--bad"], tmp_path),
    ]
    for args, cwd in cases:
        result = run_companion(args, cwd=cwd, env=env)
        assert result.returncode != 0, args
        assert "Unsupported option --bad" in result.stderr
        assert result.stdout == ""


def test_codex_new_commands_reject_unexpected_positionals(tmp_path):
    bin_dir = fake_cli_dir(tmp_path, {"plugins": []})
    env = companion_env(tmp_path, bin_dir)
    cases = [
        (["setup", "unexpected-positional", "--json"], tmp_path, "Unexpected setup argument"),
        (["doctor", "unexpected-positional", "--json"], tmp_path, "Unexpected doctor argument"),
        (["release-check", "unexpected-positional", "--json"], ROOT, "Unexpected release-check argument"),
    ]
    for args, cwd, expected_error in cases:
        result = run_companion(args, cwd=cwd, env=env)
        assert result.returncode != 0, args
        assert expected_error in result.stderr
        assert result.stdout == ""


def test_codex_command_policy_rejects_missing_value():
    result = run_companion(["setup", "--cwd"])
    assert result.returncode != 0
    assert "--cwd requires a value" in result.stderr


def test_codex_command_policy_rejects_option_token_as_value():
    result = run_companion(["setup", "--cwd", "--json"])
    assert result.returncode != 0
    assert "--cwd requires a value" in result.stderr
    assert "--cwd=--json" in result.stderr


def test_codex_command_policy_rejects_unknown_dash_token_as_value():
    result = run_companion(["setup", "--cwd", "--bogus"])
    assert result.returncode != 0
    assert "--cwd requires a value" in result.stderr
    assert "--cwd=--bogus" in result.stderr


def test_codex_command_policy_allows_equals_values_starting_with_dash():
    script = """
        import { parseStrictCommandInput } from './plugins/codex/scripts/lib/command-policy.mjs';
        const parsed = parseStrictCommandInput('review', ['--model=-1'], {
          valueOptions: ['model']
        });
        console.log(JSON.stringify(parsed));
    """
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["options"]["model"] == "-1"
    assert payload["positionals"] == []


def test_codex_new_commands_use_strict_command_parser():
    companion = read_text(PLUGIN / "scripts" / "codex-companion.mjs")
    args_module = read_text(PLUGIN / "scripts" / "lib" / "args.mjs")
    command_policy = read_text(PLUGIN / "scripts" / "lib" / "command-policy.mjs")

    assert "export function normalizeArgv" in args_module
    assert "normalizeArgv" in companion
    assert 'from "./lib/args.mjs"' in companion
    assert 'from "./args.mjs"' in command_policy
    assert "function normalizeArgv" not in companion

    for name in ["handleSetup", "handleDoctor", "handleReleaseCheck"]:
        body = js_function_body(companion, name)
        assert "parseStrictCommandInput" in body
        assert "parseCommandInput" not in body
        assert "assertKnownOptions" not in body


def test_codex_strict_parser_preserves_legacy_slash_argument_normalization():
    script = """
        import { parseArgs, normalizeArgv } from './plugins/codex/scripts/lib/args.mjs';
        import { parseStrictCommandInput } from './plugins/codex/scripts/lib/command-policy.mjs';
        const config = {
          valueOptions: ['model', 'cwd'],
          booleanOptions: ['json'],
          aliasMap: { m: 'model', C: 'cwd' }
        };
        const raw = ['-m spark --json --cwd repo focus text'];
        const tokenized = ['-m', 'spark', '--json', '--cwd', 'repo', 'focus', 'text'];
        const legacyRaw = parseArgs(normalizeArgv(raw), config);
        const legacyTokenized = parseArgs(normalizeArgv(tokenized), config);
        const strictRaw = parseStrictCommandInput('review', raw, config);
        const strictTokenized = parseStrictCommandInput('review', tokenized, config);
        console.log(JSON.stringify({ legacyRaw, legacyTokenized, strictRaw, strictTokenized }));
    """
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["legacyRaw"] == payload["legacyTokenized"]
    assert payload["strictRaw"] == payload["strictTokenized"]
    assert payload["legacyRaw"] == payload["strictRaw"]


def test_codex_strict_command_parser_preserves_aliases_and_terminator():
    script = """
        import { parseStrictCommandInput } from './plugins/codex/scripts/lib/command-policy.mjs';
        const parsed = parseStrictCommandInput('review', ['-C', 'repo', '-m', 'spark', '--', '--bad', 'focus'], {
          valueOptions: ['cwd', 'model'],
          aliasMap: { C: 'cwd', m: 'model' }
        });
        console.log(JSON.stringify(parsed));
    """
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["options"] == {"cwd": "repo", "model": "spark"}
    assert payload["positionals"] == ["--bad", "focus"]


def test_codex_setup_command_does_not_interpolate_raw_arguments():
    text = read_text(PLUGIN / "commands" / "setup.md")

    assert "disable-model-invocation" not in text
    assert "AskUserQuestion" in text
    assert "npm install -g @openai/codex" in text
    assert "$ARGUMENTS" in text
    for block in fenced_bash_blocks(text):
        assert "$ARGUMENTS" not in block
    assert 'node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" setup --json' in text
    assert (
        'node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" setup --json --enable-review-gate'
        in text
    )
    assert (
        'node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" setup --json --disable-review-gate'
        in text
    )


def test_codex_install_consistency_parses_claude_plugin_list_schema():
    script = """
        import { installedCodexEntry } from './plugins/codex/scripts/lib/install-consistency.mjs';
        const cases = [
          installedCodexEntry([{ name: 'codex', installPath: '/tmp/codex-a' }]),
          installedCodexEntry({ plugins: [{ id: 'codex@external-models-for-claude', path: '/tmp/codex-b' }] }),
          installedCodexEntry(JSON.stringify({ plugins: [{ name: 'codex', root: '/tmp/codex-c' }] })),
          installedCodexEntry({ items: [{ name: 'codex', installPath: '/tmp/wrong-shape' }] }),
          installedCodexEntry({ plugins: [{ name: 'codex', location: '/tmp/speculative' }] })
        ];
        console.log(JSON.stringify(cases));
    """
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    cases = json.loads(result.stdout)
    assert cases[0]["installPath"] == "/tmp/codex-a"
    assert cases[1]["installPath"] == "/tmp/codex-b"
    assert cases[2]["installPath"] == "/tmp/codex-c"
    assert cases[3] is None
    assert cases[4]["installPath"] == ""


def test_codex_release_check_allows_ci_placeholder_paths(tmp_path):
    repo = copy_repo(tmp_path)
    readme = repo / "README.md"
    readme.write_text(
        f"{read_text(readme)}\nCI paths: /home/runner/work/project and $RUNNER_TEMP/plugin\n",
        encoding="utf8",
    )

    payload = release_check_payload(run_release_check(repo))
    checks = checks_by_name(payload)
    assert payload["ok"] is True
    assert checks["no-machine-paths"]["ok"] is True


def test_codex_machine_path_regex_fixture_matches_python_and_release_check():
    cases = {
        "/Users/fanghao/Documents/Claude for codex": True,
        "`/Users/fanghao/private`": True,
        "`file:///Users/fanghao/private`": True,
        "[/Users/fanghao/private](https://example.com)": True,
        "[file:///Users/fanghao/private](https://example.com)": True,
        "file:///Users/fanghao/private": True,
        "<file:///Users/fanghao/private>": True,
        "file://localhost/Users/fanghao/private": True,
        "|/Users/fanghao/private|": True,
        ",/Users/fanghao/private": True,
        "{/Users/fanghao/private}": True,
        "/home/alice/project": True,
        "file:///home/alice/project": True,
        "/private/var/folders/p6/mbyd_p7d1md2wcqhq2g07tw00000gn/T/repo": True,
        "file:///private/var/folders/p6/mbyd_p7d1md2wcqhq2g07tw00000gn/T/repo": True,
        "<file:///private/var/folders/p6/mbyd_p7d1md2wcqhq2g07tw00000gn/T/repo>": True,
        "/var/folders/p6/mbyd_p7d1md2wcqhq2g07tw00000gn/T/repo": True,
        "file:///var/folders/p6/mbyd_p7d1md2wcqhq2g07tw00000gn/T/repo": True,
        "/Volumes/Workspace/project": True,
        "file:///Volumes/Workspace/project": True,
        "<file:///Volumes/Workspace/project>": True,
        "/Volumes/Macintosh HD/project": True,
        "`/Volumes/Macintosh HD/project`": True,
        "file:///Volumes/Macintosh%20HD/project": True,
        "`file:///Volumes/Macintosh%20HD/project`": True,
        "[file:///Volumes/Macintosh%20HD/project](https://example.com)": True,
        "<file:///Volumes/Macintosh%20HD/project>": True,
        r"C:\Users\Jane Doe\AppData\Local\Temp\repo": True,
        "C:/Users/Jane Doe/AppData/Local/Temp/repo": True,
        "file:///C:/Users/Jane%20Doe/AppData/Local/Temp/repo": True,
        "<file:///C:/Users/Jane%20Doe/AppData/Local/Temp/repo>": True,
        "file://localhost/C:/Users/Jane%20Doe/AppData/Local/Temp/repo": True,
        "/home/runner/work/external-models-for-claude": False,
        "file:///home/runner/work/external-models-for-claude": False,
        "/home/vscode/workspace": False,
        "/home/ubuntu/project": False,
        "/home/circleci/project": False,
        "/home/runneradmin/project": False,
        "/Volumes/<Disk>/project": False,
        "/Volumes/${VOLUME}/project": False,
        "C:/Users/<username>/project": False,
        "file:///C:/Users/<username>/project": False,
        r"\\server\share\project": False,
        "file://server/share/project": False,
        "<home>/project": False,
        "$RUNNER_TEMP/plugin": False,
    }
    script = """
        import { hasMachinePath } from './plugins/codex/scripts/lib/path-hygiene.mjs';
        const cases = JSON.parse(process.argv[1]);
        console.log(JSON.stringify(cases.map((text) => hasMachinePath(text))));
    """
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script, json.dumps(list(cases))],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    js_results = json.loads(result.stdout)

    for (text, expected), js_result in zip(cases.items(), js_results):
        assert bool(MACHINE_PATH_PATTERN.search(text)) is expected, text
        assert js_result is expected, text


def test_codex_machine_path_pattern_source_is_single_contract():
    path_hygiene = read_text(PLUGIN / "scripts" / "lib" / "path-hygiene.mjs")
    assert "MACHINE_PATH_PATTERN_SOURCE" in path_hygiene
    assert "new RegExp(MACHINE_PATH_PATTERN_SOURCE" in path_hygiene
    assert "function hasMachinePath" in path_hygiene

    if RELEASE_CHECK_MODULE.exists():
        release_check = read_text(RELEASE_CHECK_MODULE)
        assert "MACHINE_PATH_PATTERN_SOURCE" in release_check
        assert "hasMachinePath" in release_check
        assert "new RegExp" not in release_check
        assert "/Users/" not in release_check
        assert "/private/var/folders" not in release_check
        assert "/Volumes/" not in release_check


def governor_env(tmp_path, **overrides):
    env = {
        "CODEX_FOR_CLAUDE_RESOURCE_LOCK_DIR": str(tmp_path / "locks"),
        "CLAUDE_PLUGIN_DATA": str(tmp_path / "plugin-data"),
    }
    env.update(overrides)
    return env


def background_launch_failure_payload(tmp_path, mode):
    return run_node_script(
        """
        import fs from 'node:fs';
        import { __testHooks } from './plugins/codex/scripts/codex-companion.mjs';
        import { listJobs, resolveJobFile } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const mode = process.argv[2];
        const job = {
          id: `task-${mode}`,
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Codex Task',
          summary: mode,
          write: true,
          sessionId: 'session-failure',
          workspaceRoot: cwd
        };
        const request = {
          cwd,
          model: null,
          effort: null,
          prompt: `launch failure ${mode}`,
          write: false,
          resumeLast: false,
          jobId: job.id
        };
        const lease = {
          disabled: false,
          lease: { id: `background-job-${mode}` },
          released: false,
          release() {
            this.released = true;
          }
        };
        const dependencies = {
          spawnTaskWorker() {
            if (mode === 'spawn') {
              throw new Error('spawn failed');
            }
            return mode === 'pid' ? { pid: null } : { pid: 12345 };
          },
          transferResourceLease() {
            return false;
          }
        };

        let errorMessage = null;
        try {
          __testHooks.enqueueBackgroundTask(cwd, job, request, lease, dependencies);
        } catch (error) {
          errorMessage = error.message;
        }
        const jobs = listJobs(cwd);
        const sharedJob = jobs.find((item) => item.id === job.id);
        const activeJobs = jobs.filter((item) => item.status === 'queued' || item.status === 'running');
        const stored = JSON.parse(fs.readFileSync(resolveJobFile(cwd, job.id), 'utf8'));
        console.log(JSON.stringify({
          errorMessage,
          released: lease.released,
          activeCount: activeJobs.length,
          sharedJob,
          status: sharedJob?.status,
          storedStatus: stored.status,
          storedPhase: stored.phase
        }));
        """,
        env=governor_env(tmp_path),
        args=[str(tmp_path), mode],
    )


def test_codex_resource_governor_blocks_without_leaking_lock_root(tmp_path):
    payload = run_node_script(
        """
        import { acquireResourceLease, capacityBlockedMessage } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const lease = acquireResourceLease('model-call', { env: process.env, limit: 0, command: 'test' });
        console.log(JSON.stringify({ ok: lease.ok, message: capacityBlockedMessage(lease), lockDir: process.env.CODEX_FOR_CLAUDE_RESOURCE_LOCK_DIR }));
        """,
        env=governor_env(tmp_path),
    )
    assert payload["ok"] is False
    assert payload["message"].startswith("capacity_blocked: codex model-call capacity is full (0/0)")
    assert payload["lockDir"] not in payload["message"]


def test_codex_resource_governor_wrapper_is_thin_shared_core_adapter():
    text = read_text(PLUGIN / "scripts" / "lib" / "resource-governor.mjs")
    assert "createResourceGovernor({" in text
    assert text.count("createResourceGovernor") == 2
    assert "CODEX_FOR_CLAUDE" in text
    assert "function acquireResourceLease" not in text


def test_codex_resource_governor_wrapper_imports_shared_core():
    text = read_text(PLUGIN / "scripts" / "lib" / "resource-governor.mjs")
    assert 'from "./resource-governor-core.mjs"' in text


def test_codex_resource_governor_factory_exposes_codex_capacity_contract(tmp_path):
    payload = run_node_script(
        """
        import { createResourceGovernor } from './plugins/codex/scripts/lib/resource-governor-core.mjs';
        const governor = createResourceGovernor({
          envPrefix: 'TEST_CODEX',
          capacityLabel: 'codex',
          defaultModelLimit: 2,
          defaultBackgroundLimit: 4,
          defaultStopGateLimit: 1,
          homeStateDir: '.test-codex-locks'
        });
        const lease = governor.acquireResourceLease('model-call', { env: process.env, limit: 0 });
        console.log(JSON.stringify({ lease, result: governor.capacityBlockedResult(lease) }));
        """,
        env={"TEST_CODEX_RESOURCE_LOCK_DIR": str(tmp_path / "locks")},
    )
    assert payload["result"]["status"] == 75
    assert payload["result"]["errorCode"] == "ECAPACITY"
    assert payload["result"]["stderr"].startswith("capacity_blocked: codex model-call capacity is full")


def test_codex_resource_governor_core_is_vendored_without_provider_runtime_leakage():
    text = read_text(PLUGIN / "scripts" / "lib" / "resource-governor-core.mjs")
    stripped = re.sub(r"/\\*.*?\\*/|//.*?$", "", text, flags=re.DOTALL | re.MULTILINE)
    for forbidden in [
        "CODEX_FOR_CLAUDE",
        "GEMINI",
        "ANTIGRAVITY",
        "claude-for-codex",
        "gemini-for-claude",
        "antigravity-for-claude",
    ]:
        assert forbidden not in stripped


def test_codex_resource_governor_provenance_is_shipped_in_notices():
    phrase = "ported from fanghao's Gemini/Antigravity governor work covered by this repository's root MIT license"
    for path in [
        PLUGIN / "scripts" / "lib" / "resource-governor-core.mjs",
        PLUGIN / "FORK_NOTICE.md",
        ROOT / "THIRD_PARTY_NOTICES.md",
    ]:
        text = read_text(path)
        assert phrase in text
        assert "Codex-specific additions" in text


def test_codex_resource_governor_enforces_limit_concurrently(tmp_path):
    payload = run_node_script(
        """
        import { acquireResourceLease } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const first = acquireResourceLease('model-call', { env: process.env, limit: 1 });
        const second = acquireResourceLease('model-call', { env: process.env, limit: 1 });
        first.release();
        console.log(JSON.stringify({ firstOk: first.ok, secondOk: second.ok, active: second.active, limit: second.limit }));
        """,
        env=governor_env(tmp_path),
    )
    assert payload == {"firstOk": True, "secondOk": False, "active": 1, "limit": 1}


def test_codex_stop_gate_pool_is_independent_from_model_call_capacity(tmp_path):
    payload = run_node_script(
        """
        import { acquireResourceLease } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const model = acquireResourceLease('model-call', { env: process.env, limit: 0 });
        const stopGate = acquireResourceLease('stop-gate', { env: process.env });
        stopGate.release();
        console.log(JSON.stringify({ modelOk: model.ok, stopGateOk: stopGate.ok, stopGateKind: stopGate.lease.kind }));
        """,
        env=governor_env(tmp_path),
    )
    assert payload == {"modelOk": False, "stopGateOk": True, "stopGateKind": "stop-gate"}


def test_codex_resource_governor_verify_expected_command_rejects_mismatch(tmp_path):
    payload = run_node_script(
        """
        import { acquireResourceLease, verifyResourceLease } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const lease = acquireResourceLease('stop-gate', { env: process.env, command: 'stop-review-gate' });
        const matching = verifyResourceLease(lease.lease.id, 'stop-gate', { env: process.env, expectedCommand: 'stop-review-gate' });
        const mismatched = verifyResourceLease(lease.lease.id, 'stop-gate', { env: process.env, expectedCommand: 'task' });
        lease.release();
        console.log(JSON.stringify({ matchingOk: matching.ok, mismatchedOk: mismatched.ok, reason: mismatched.reason }));
        """,
        env=governor_env(tmp_path),
    )
    assert payload == {
        "matchingOk": True,
        "mismatchedOk": False,
        "reason": "resource lease command mismatch",
    }


def test_codex_resource_governor_verify_expected_parent_pid_uses_owner_or_holder(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import path from 'node:path';
        import { acquireResourceLease, resourceLockRoot, verifyResourceLease } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const lease = acquireResourceLease('stop-gate', { env: process.env, command: 'stop-review-gate' });
        const file = path.join(resourceLockRoot(process.env), `${lease.lease.id}.json`);
        const ownerMatch = verifyResourceLease(lease.lease.id, 'stop-gate', { env: process.env, expectedParentPid: process.pid });
        const mismatch = verifyResourceLease(lease.lease.id, 'stop-gate', { env: process.env, expectedParentPid: process.pid + 100000 });
        const withoutOwner = JSON.parse(fs.readFileSync(file, 'utf8'));
        delete withoutOwner.ownerPid;
        fs.writeFileSync(file, `${JSON.stringify(withoutOwner, null, 2)}\\n`);
        const holderFallback = verifyResourceLease(lease.lease.id, 'stop-gate', { env: process.env, expectedParentPid: process.pid });
        const deadOwner = JSON.parse(fs.readFileSync(file, 'utf8'));
        deadOwner.ownerPid = 99999999;
        fs.writeFileSync(file, `${JSON.stringify(deadOwner, null, 2)}\\n`);
        const deadParent = verifyResourceLease(lease.lease.id, 'stop-gate', { env: process.env, expectedParentPid: 99999999 });
        lease.release();
        console.log(JSON.stringify({
          ownerMatchOk: ownerMatch.ok,
          mismatchOk: mismatch.ok,
          mismatchReason: mismatch.reason,
          holderFallbackOk: holderFallback.ok,
          deadParentOk: deadParent.ok,
          deadParentReason: deadParent.reason
        }));
        """,
        env=governor_env(tmp_path),
    )
    assert payload["ownerMatchOk"] is True
    assert payload["mismatchOk"] is False
    assert payload["mismatchReason"] == "resource lease parent pid mismatch"
    assert payload["holderFallbackOk"] is True
    assert payload["deadParentOk"] is False
    assert payload["deadParentReason"] == "resource lease parent is not alive"


def test_codex_default_model_limit_two_can_saturate_foreground_pool(tmp_path):
    payload = run_node_script(
        """
        import { acquireResourceLease } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const first = acquireResourceLease('model-call', { env: process.env });
        const second = acquireResourceLease('model-call', { env: process.env });
        const third = acquireResourceLease('model-call', { env: process.env });
        first.release();
        second.release();
        console.log(JSON.stringify({ first: first.ok, second: second.ok, third: third.ok, active: third.active, limit: third.limit }));
        """,
        env=governor_env(tmp_path),
    )
    assert payload == {"first": True, "second": True, "third": False, "active": 2, "limit": 2}


def test_codex_review_job_metadata_and_creation_are_pure_before_foreground_run():
    body = js_function_body(read_text(PLUGIN / "scripts" / "codex-companion.mjs"), "handleReviewCommand")
    assert body.index('acquireResourceLease("model-call"') < body.index("const focusText")
    assert body.index('acquireResourceLease("model-call"') < body.index("resolveReviewTarget")
    assert body.index('acquireResourceLease("model-call"') < body.index("buildReviewJobMetadata")
    assert body.index('acquireResourceLease("model-call"') < body.index("createCompanionJob")


def test_codex_review_capacity_zero_returns_capacity_blocked(tmp_path):
    result = run_companion(
        ["review", "--json"],
        cwd=tmp_path,
        env=governor_env(tmp_path, CODEX_FOR_CLAUDE_GLOBAL_MAX_MODEL_CALLS="0"),
    )
    assert result.returncode == 75
    assert "capacity_blocked: codex model-call capacity is full (0/0)" in result.stderr
    assert "This command must run inside a Git repository" not in result.stderr


def test_codex_task_capacity_zero_returns_capacity_blocked(tmp_path):
    result = run_companion(
        ["task", "--json", "do work"],
        cwd=tmp_path,
        env=governor_env(tmp_path, CODEX_FOR_CLAUDE_GLOBAL_MAX_MODEL_CALLS="0"),
    )
    assert result.returncode == 75
    assert "capacity_blocked: codex model-call capacity is full (0/0)" in result.stderr


def test_codex_background_task_capacity_zero_returns_capacity_blocked_before_codex_probe(tmp_path):
    result = run_companion(
        ["task", "--background", "--json", "do work"],
        cwd=tmp_path,
        env=governor_env(tmp_path, CODEX_FOR_CLAUDE_GLOBAL_MAX_BACKGROUND_JOBS="0", PATH=""),
    )
    assert result.returncode == 75
    assert "capacity_blocked: codex background-job capacity is full (0/0)" in result.stderr
    assert "Install Codex" not in result.stderr


def test_codex_workspace_root_resolves_non_git_for_capacity_precedence(tmp_path):
    result = run_companion(
        ["review", "--json"],
        cwd=tmp_path,
        env=governor_env(tmp_path, CODEX_FOR_CLAUDE_GLOBAL_MAX_MODEL_CALLS="0"),
    )
    assert result.returncode == 75
    assert "capacity_blocked" in result.stderr


def test_codex_command_workspace_resolution_uses_workspace_fallback_contract(tmp_path):
    payload = json.loads(run_companion(["status", "--json"], cwd=tmp_path, env=governor_env(tmp_path)).stdout)
    assert payload["workspaceRoot"] == str(tmp_path)


def test_codex_status_cleanup_failure_is_advisory_and_sanitized(tmp_path):
    lock_file = tmp_path / "lock-root-file"
    lock_file.write_text("not a directory\n", encoding="utf8")

    result = run_companion(
        ["status", "--json"],
        cwd=tmp_path,
        env=governor_env(tmp_path, CODEX_FOR_CLAUDE_RESOURCE_LOCK_DIR=str(lock_file)),
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["workspaceRoot"] == str(tmp_path)
    assert str(lock_file) not in result.stderr
    assert str(lock_file) not in result.stdout


def test_codex_background_lease_released_when_worker_spawn_fails():
    body = js_function_body(read_text(PLUGIN / "scripts" / "codex-companion.mjs"), "enqueueBackgroundTask")
    assert "try" in body
    assert "spawnDetachedTaskWorker" in body
    assert "backgroundLease.release()" in body


def test_codex_background_missing_worker_pid_releases_lease_once():
    body = js_function_body(read_text(PLUGIN / "scripts" / "codex-companion.mjs"), "enqueueBackgroundTask")
    assert "child.pid" in body
    assert "backgroundLease.release()" in body
    assert body.index("!Number.isInteger(child.pid)") < body.index("transferLease(backgroundLease")
    assert body.count("backgroundLease.release()") == 1


def test_codex_background_launch_failures_do_not_leave_active_jobs(tmp_path):
    for mode in ["spawn", "pid", "transfer"]:
        payload = background_launch_failure_payload(tmp_path, mode)
        assert payload["released"] is True
        assert payload["activeCount"] == 0
        assert payload["status"] == "failed"
        assert payload["sharedJob"]["jobClass"] == "task"
        assert payload["sharedJob"]["title"] == "Codex Task"
        assert payload["sharedJob"]["summary"] == mode
        assert payload["sharedJob"]["write"] is True
        assert payload["sharedJob"]["sessionId"] == "session-failure"
        assert "request" not in payload["sharedJob"]
        assert "backgroundLeaseId" not in payload["sharedJob"]
        assert payload["storedStatus"] == "failed"
        assert payload["storedPhase"] == "failed"
        assert payload["errorMessage"]


def test_codex_background_enqueue_success_preserves_sanitized_shared_metadata(tmp_path):
    payload = run_node_script(
        """
        import { __testHooks } from './plugins/codex/scripts/codex-companion.mjs';
        import { listJobs, resolveJobFile } from './plugins/codex/scripts/lib/state.mjs';
        import fs from 'node:fs';

        const cwd = process.argv[1];
        const job = {
          id: 'task-success',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Codex Task: success',
          summary: 'successful background metadata',
          write: true,
          sessionId: 'session-success',
          workspaceRoot: cwd
        };
        const request = {
          cwd,
          model: null,
          effort: null,
          prompt: 'successful background metadata',
          write: true,
          resumeLast: false,
          jobId: job.id
        };
        const lease = {
          disabled: false,
          lease: { id: 'background-job-success' },
          released: false,
          release() {
            this.released = true;
          }
        };
        const result = __testHooks.enqueueBackgroundTask(cwd, job, request, lease, {
          spawnTaskWorker() {
            return { pid: 12345 };
          },
          transferResourceLease() {
            return true;
          }
        });
        const sharedJob = listJobs(cwd).find((item) => item.id === job.id);
        const stored = JSON.parse(fs.readFileSync(resolveJobFile(cwd, job.id), 'utf8'));
        console.log(JSON.stringify({
          payload: result.payload,
          released: lease.released,
          sharedJob,
          storedRequestBackgroundLeaseId: stored.request.backgroundLeaseId
        }));
        """,
        env=governor_env(tmp_path),
        args=[str(tmp_path)],
    )
    shared_job = payload["sharedJob"]
    assert payload["released"] is False
    assert shared_job["jobClass"] == "task"
    assert shared_job["kind"] == "task"
    assert shared_job["kindLabel"] == "rescue"
    assert shared_job["title"] == "Codex Task: success"
    assert shared_job["summary"] == "successful background metadata"
    assert shared_job["write"] is True
    assert shared_job["sessionId"] == "session-success"
    assert shared_job["status"] == "queued"
    assert shared_job["phase"] == "queued"
    assert shared_job["pid"] == 12345
    assert shared_job["governorVersion"] == 1
    assert "request" not in shared_job
    assert "backgroundLeaseId" not in shared_job
    assert payload["storedRequestBackgroundLeaseId"] == "background-job-success"


def test_codex_task_worker_preserves_stored_job_bindings_before_claim():
    body = js_function_body(read_text(PLUGIN / "scripts" / "codex-companion.mjs"), "handleTaskWorker")
    assert body.index("const storedJob") < body.index("const request")
    assert body.index("const request") < body.index("claimResourceLease")
    assert body.index("const workspaceRoot") < body.index("claimResourceLease")


def test_codex_foreground_task_does_not_acquire_background_job_lease():
    body = js_function_body(read_text(PLUGIN / "scripts" / "codex-companion.mjs"), "handleTask")
    foreground = body.split("if (options.background)", 1)[1].split("const foregroundJob", 1)[1]
    assert 'acquireResourceLease("background-job"' not in foreground
    assert "withResourceLease" in foreground
    assert '"model-call"' in foreground


def test_codex_resource_governor_off_makes_claim_and_transfer_noops(tmp_path):
    payload = run_node_script(
        """
        import { claimResourceLease, transferResourceLease } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const claimed = claimResourceLease('missing-id', 'background-job', process.env);
        const transferred = transferResourceLease('', 0, process.env);
        console.log(JSON.stringify({ claimedOk: claimed.ok, disabled: claimed.disabled, transferred }));
        """,
        env=governor_env(tmp_path, CODEX_FOR_CLAUDE_RESOURCE_GOVERNOR="off"),
    )
    assert payload == {"claimedOk": True, "disabled": True, "transferred": True}


def test_codex_task_worker_governor_off_allows_v1_job_with_null_background_lease(tmp_path):
    bin_dir = fake_cli_dir(tmp_path, {"plugins": []})
    env = companion_env(tmp_path, bin_dir)
    env.update(
        governor_env(
            tmp_path,
            CODEX_FOR_CLAUDE_RESOURCE_GOVERNOR="off",
        )
    )
    run_node_script(
        """
        import { upsertJob, writeJobFile } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        const job = {
          id: 'task-offmode',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Codex Task',
          summary: 'off mode',
          status: 'queued',
          phase: 'queued',
          pid: null,
          logFile: null,
          workspaceRoot: cwd,
          governorVersion: 1,
          request: {
            cwd,
            model: null,
            effort: null,
            prompt: 'off mode worker regression',
            write: false,
            resumeLast: false,
            jobId: 'task-offmode',
            backgroundLeaseId: null
          }
        };
        upsertJob(cwd, {
          id: job.id,
          status: job.status,
          phase: job.phase,
          pid: job.pid,
          logFile: job.logFile
        });
        writeJobFile(cwd, job.id, job);
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    result = run_companion(["task-worker", "--cwd", str(tmp_path), "--job-id", "task-offmode"], cwd=tmp_path, env=env)

    assert "missing its background resource lease" not in result.stderr


def test_codex_task_worker_shared_state_stays_request_free_after_update(tmp_path):
    bin_dir = fake_cli_dir(tmp_path, {"plugins": []})
    env = companion_env(tmp_path, bin_dir)
    env.update(governor_env(tmp_path, CODEX_FOR_CLAUDE_RESOURCE_GOVERNOR="off"))
    run_node_script(
        """
        import { upsertJob, writeJobFile } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        const now = new Date().toISOString();
        const job = {
          id: 'task-worker-sanitize',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Codex Task',
          summary: 'worker sanitize',
          status: 'queued',
          phase: 'queued',
          pid: null,
          logFile: null,
          workspaceRoot: cwd,
          createdAt: now,
          updatedAt: now,
          governorVersion: 1,
          write: true,
          sessionId: 'session-worker-sanitize',
          backgroundLeaseId: 'top-level-background-lease',
          backgroundLease: { lease: { id: 'nested-background-lease' } },
          lease: { id: 'raw-lease-detail' },
          request: {
            cwd,
            model: null,
            effort: null,
            prompt: 'worker sanitize',
            write: true,
            resumeLast: false,
            jobId: 'task-worker-sanitize',
            backgroundLeaseId: 'request-background-lease'
          }
        };
        upsertJob(cwd, {
          id: job.id,
          kind: job.kind,
          kindLabel: job.kindLabel,
          jobClass: job.jobClass,
          title: job.title,
          summary: job.summary,
          status: job.status,
          phase: job.phase,
          pid: job.pid,
          logFile: job.logFile,
          workspaceRoot: job.workspaceRoot,
          governorVersion: job.governorVersion,
          write: job.write,
          sessionId: job.sessionId,
          createdAt: now,
          updatedAt: now
        });
        writeJobFile(cwd, job.id, job);
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    result = run_companion(["task-worker", "--cwd", str(tmp_path), "--job-id", "task-worker-sanitize"], cwd=tmp_path, env=env)
    payload = run_node_script(
        """
        import { listJobs } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        const sharedJob = listJobs(cwd).find((item) => item.id === 'task-worker-sanitize');
        console.log(JSON.stringify({ sharedJob }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    assert "missing its background resource lease" not in result.stderr
    shared_job = payload["sharedJob"]
    assert shared_job["jobClass"] == "task"
    assert shared_job["kind"] == "task"
    assert shared_job["kindLabel"] == "rescue"
    assert shared_job["title"] == "Codex Task"
    assert shared_job["summary"] == "worker sanitize"
    assert shared_job["write"] is True
    assert shared_job["sessionId"] == "session-worker-sanitize"
    assert shared_job["status"] == "failed"
    assert "request" not in shared_job
    assert "backgroundLeaseId" not in shared_job
    assert "backgroundLease" not in shared_job
    assert "lease" not in shared_job


def test_codex_background_lease_claim_is_unconditional_for_existing_counted_lease(tmp_path):
    payload = run_node_script(
        """
        import { acquireResourceLease, claimResourceLease } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const lease = acquireResourceLease('background-job', { env: process.env, limit: 1, transferable: true, pid: 0 });
        const claimed = claimResourceLease(lease.lease.id, 'background-job', process.env);
        claimed.release();
        console.log(JSON.stringify({ acquired: lease.ok, claimed: claimed.ok }));
        """,
        env=governor_env(tmp_path, CODEX_FOR_CLAUDE_GLOBAL_MAX_BACKGROUND_JOBS="1"),
    )
    assert payload == {"acquired": True, "claimed": True}


def test_codex_background_lease_claim_allows_active_equal_limit(tmp_path):
    test_codex_background_lease_claim_is_unconditional_for_existing_counted_lease(tmp_path)


def test_codex_task_worker_reacquire_capacity_blocked_is_explicit():
    body = js_function_body(read_text(PLUGIN / "scripts" / "codex-companion.mjs"), "handleTaskWorker")
    assert "task-worker-reclaim" in body
    assert "ECAPACITY" in body
    assert "capacityBlockedMessage" in body


def test_codex_task_worker_rejects_fresh_unclaimable_handoff(tmp_path):
    env = governor_env(tmp_path)
    payload = run_node_script(
        """
        import { acquireResourceLease } from './plugins/codex/scripts/lib/resource-governor.mjs';
        import { upsertJob, writeJobFile } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const lease = acquireResourceLease('background-job', {
          env: process.env,
          transferable: true,
          pid: 0,
          command: 'task-worker',
          jobId: 'task-fresh-handoff'
        });
        const leaseId = lease.lease.id;
        lease.release();
        const now = new Date().toISOString();
        const job = {
          id: 'task-fresh-handoff',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Codex Task',
          summary: 'fresh handoff',
          status: 'queued',
          phase: 'queued',
          pid: null,
          logFile: null,
          workspaceRoot: cwd,
          createdAt: now,
          updatedAt: now,
          governorVersion: 1,
          request: {
            cwd,
            model: null,
            effort: null,
            prompt: 'fresh handoff',
            write: false,
            resumeLast: false,
            jobId: 'task-fresh-handoff',
            backgroundLeaseId: leaseId
          }
        };
        upsertJob(cwd, {
          id: job.id,
          status: job.status,
          phase: job.phase,
          pid: job.pid,
          logFile: job.logFile,
          createdAt: now,
          updatedAt: now
        });
        writeJobFile(cwd, job.id, job);
        console.log(JSON.stringify({ leaseId }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    result = run_companion(["task-worker", "--cwd", str(tmp_path), "--job-id", "task-fresh-handoff"], cwd=tmp_path, env=env)

    assert payload["leaseId"].startswith("background-job-")
    assert result.returncode == 1
    assert "lease is not claimable" in result.stderr
    assert "task-worker-reclaim" not in result.stderr


def test_codex_task_worker_rejects_already_claimed_handoff_even_when_old(tmp_path):
    env = governor_env(tmp_path)
    run_node_script(
        """
        import fs from 'node:fs';
        import path from 'node:path';
        import {
          acquireResourceLease,
          claimResourceLease,
          resourceLockRoot
        } from './plugins/codex/scripts/lib/resource-governor.mjs';
        import { upsertJob, writeJobFile } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const old = new Date(Date.now() - 60000).toISOString();
        const lease = acquireResourceLease('background-job', {
          env: process.env,
          transferable: true,
          pid: 0,
          command: 'task-worker',
          jobId: 'task-claimed-handoff'
        });
        const claimed = claimResourceLease(lease.lease.id, 'background-job', process.env);
        const file = path.join(resourceLockRoot(process.env), `${lease.lease.id}.json`);
        const leasePayload = JSON.parse(fs.readFileSync(file, 'utf8'));
        fs.writeFileSync(file, `${JSON.stringify({
          ...leasePayload,
          pid: 99999999,
          ownerPid: 99999999,
          transferable: false
        }, null, 2)}\\n`);
        const job = {
          id: 'task-claimed-handoff',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Codex Task',
          summary: 'claimed handoff',
          status: 'queued',
          phase: 'queued',
          pid: null,
          logFile: null,
          workspaceRoot: cwd,
          createdAt: old,
          updatedAt: old,
          governorVersion: 1,
          request: {
            cwd,
            model: null,
            effort: null,
            prompt: 'claimed handoff',
            write: false,
            resumeLast: false,
            jobId: 'task-claimed-handoff',
            backgroundLeaseId: lease.lease.id
          }
        };
        upsertJob(cwd, {
          id: job.id,
          status: job.status,
          phase: job.phase,
          pid: job.pid,
          logFile: job.logFile,
          createdAt: old,
          updatedAt: old
        });
        writeJobFile(cwd, job.id, job);
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    result = run_companion(["task-worker", "--cwd", str(tmp_path), "--job-id", "task-claimed-handoff"], cwd=tmp_path, env=env)

    assert result.returncode == 1
    assert "lease is not claimable" in result.stderr
    assert "Codex CLI is not installed" not in result.stderr


def test_codex_task_worker_reclaims_only_stale_handoff_without_active_lease(tmp_path):
    env = governor_env(tmp_path, PATH="")
    run_node_script(
        """
        import fs from 'node:fs';
        import path from 'node:path';
        import { acquireResourceLease, resourceLockRoot } from './plugins/codex/scripts/lib/resource-governor.mjs';
        import { upsertJob, writeJobFile } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const old = new Date(Date.now() - 60000).toISOString();
        const lease = acquireResourceLease('background-job', {
          env: process.env,
          transferable: true,
          pid: 0,
          command: 'task-worker',
          jobId: 'task-stale-handoff'
        });
        const leaseId = lease.lease.id;
        const file = path.join(resourceLockRoot(process.env), `${leaseId}.json`);
        const leasePayload = JSON.parse(fs.readFileSync(file, 'utf8'));
        fs.writeFileSync(file, `${JSON.stringify({
          ...leasePayload,
          pid: 0,
          ownerPid: 99999999,
          transferable: true,
          claimedAt: undefined,
          claimedAtMs: undefined
        }, null, 2)}\\n`);
        const job = {
          id: 'task-stale-handoff',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Codex Task',
          summary: 'stale handoff',
          status: 'queued',
          phase: 'queued',
          pid: null,
          logFile: null,
          workspaceRoot: cwd,
          createdAt: old,
          updatedAt: old,
          governorVersion: 1,
          request: {
            cwd,
            model: null,
            effort: null,
            prompt: 'stale handoff',
            write: false,
            resumeLast: false,
            jobId: 'task-stale-handoff',
            backgroundLeaseId: leaseId
          }
        };
        upsertJob(cwd, {
          id: job.id,
          status: job.status,
          phase: job.phase,
          pid: job.pid,
          logFile: job.logFile,
          createdAt: old,
          updatedAt: old
        });
        writeJobFile(cwd, job.id, job);
        console.log(JSON.stringify({ leaseId }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    result = run_companion(["task-worker", "--cwd", str(tmp_path), "--job-id", "task-stale-handoff"], cwd=tmp_path, env=env)

    assert result.returncode == 1
    assert "lease is not claimable" not in result.stderr
    assert "Codex CLI is not installed" in result.stderr


def test_codex_background_lease_claim_then_release_frees_slot(tmp_path):
    payload = run_node_script(
        """
        import { acquireResourceLease, claimResourceLease } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const first = acquireResourceLease('background-job', { env: process.env, limit: 1, transferable: true, pid: 0 });
        const claimed = claimResourceLease(first.lease.id, 'background-job', process.env);
        claimed.release();
        const second = acquireResourceLease('background-job', { env: process.env, limit: 1 });
        second.release();
        console.log(JSON.stringify({ first: first.ok, claimed: claimed.ok, second: second.ok }));
        """,
        env=governor_env(tmp_path),
    )
    assert payload == {"first": True, "claimed": True, "second": True}


def test_codex_background_claimed_lease_cannot_be_reopened_by_transfer(tmp_path):
    payload = run_node_script(
        """
        import { acquireResourceLease, claimResourceLease, transferResourceLease } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const first = acquireResourceLease('background-job', { env: process.env, limit: 1, transferable: true, pid: 0 });
        const claimed = claimResourceLease(first.lease.id, 'background-job', process.env);
        const transferredAfterClaim = transferResourceLease(first.lease.id, process.pid, process.env, { keepTransferable: true });
        const duplicateClaim = claimResourceLease(first.lease.id, 'background-job', process.env);
        claimed.release();
        console.log(JSON.stringify({
          firstOk: first.ok,
          claimedOk: claimed.ok,
          transferredAfterClaim,
          duplicateClaimOk: duplicateClaim.ok,
          duplicateClaimReason: duplicateClaim.reason
        }));
        """,
        env=governor_env(tmp_path),
    )
    assert payload == {
        "firstOk": True,
        "claimedOk": True,
        "transferredAfterClaim": True,
        "duplicateClaimOk": False,
        "duplicateClaimReason": "lease is not claimable",
    }


def test_codex_background_transferred_dead_pid_reaps_on_next_governor_operation(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import path from 'node:path';
        import { acquireResourceLease, transferResourceLease, resourceLockRoot } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const first = acquireResourceLease('background-job', { env: process.env, limit: 1, transferable: true });
        transferResourceLease(first.lease.id, 99999999, process.env);
        const file = path.join(resourceLockRoot(process.env), `${first.lease.id}.json`);
        const lease = JSON.parse(fs.readFileSync(file, 'utf8'));
        lease.transferredAtMs = Date.now() - 31000;
        fs.writeFileSync(file, `${JSON.stringify(lease, null, 2)}\\n`);
        const second = acquireResourceLease('background-job', { env: process.env, limit: 1 });
        second.release();
        console.log(JSON.stringify({ second: second.ok }));
        """,
        env=governor_env(tmp_path),
    )
    assert payload == {"second": True}


def test_codex_background_transferred_lease_has_claim_grace(tmp_path):
    payload = run_node_script(
        """
        import { acquireResourceLease, transferResourceLease } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const first = acquireResourceLease('background-job', { env: process.env, limit: 1, transferable: true });
        transferResourceLease(first.lease.id, 99999999, process.env, { keepTransferable: true });
        const second = acquireResourceLease('background-job', { env: process.env, limit: 1 });
        first.release();
        console.log(JSON.stringify({ second: second.ok, active: second.active }));
        """,
        env=governor_env(tmp_path),
    )
    assert payload == {"second": False, "active": 1}


def test_codex_background_transferred_alive_child_dead_owner_is_not_reaped_during_grace(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import path from 'node:path';
        import { acquireResourceLease, transferResourceLease, resourceLockRoot } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const first = acquireResourceLease('background-job', { env: process.env, limit: 1, transferable: true });
        transferResourceLease(first.lease.id, process.pid, process.env, { keepTransferable: true });
        const file = path.join(resourceLockRoot(process.env), `${first.lease.id}.json`);
        const lease = JSON.parse(fs.readFileSync(file, 'utf8'));
        lease.ownerPid = 99999999;
        fs.writeFileSync(file, `${JSON.stringify(lease, null, 2)}\\n`);
        const second = acquireResourceLease('background-job', { env: process.env, limit: 1 });
        first.release();
        console.log(JSON.stringify({ second: second.ok, active: second.active }));
        """,
        env=governor_env(tmp_path),
    )
    assert payload == {"second": False, "active": 1}


def test_codex_background_unspawned_dead_owner_reaps_without_grace(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import path from 'node:path';
        import { acquireResourceLease, resourceLockRoot } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const first = acquireResourceLease('background-job', { env: process.env, limit: 1, transferable: true, pid: 0 });
        const file = path.join(resourceLockRoot(process.env), `${first.lease.id}.json`);
        const lease = JSON.parse(fs.readFileSync(file, 'utf8'));
        lease.ownerPid = 99999999;
        fs.writeFileSync(file, `${JSON.stringify(lease, null, 2)}\\n`);
        const second = acquireResourceLease('background-job', { env: process.env, limit: 1 });
        second.release();
        console.log(JSON.stringify({ second: second.ok }));
        """,
        env=governor_env(tmp_path),
    )
    assert payload == {"second": True}


def test_codex_background_unspawned_live_owner_is_not_reaped_by_age_only(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import path from 'node:path';
        import { acquireResourceLease, resourceLockRoot } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const first = acquireResourceLease('background-job', { env: process.env, limit: 1, transferable: true, pid: 0 });
        const file = path.join(resourceLockRoot(process.env), `${first.lease.id}.json`);
        const lease = JSON.parse(fs.readFileSync(file, 'utf8'));
        lease.createdAtMs = Date.now() - 10 * 60 * 1000;
        lease.updatedAtMs = lease.createdAtMs;
        fs.writeFileSync(file, `${JSON.stringify(lease, null, 2)}\\n`);
        const second = acquireResourceLease('background-job', { env: process.env, limit: 1 });
        first.release();
        console.log(JSON.stringify({ second: second.ok, active: second.active }));
        """,
        env=governor_env(tmp_path),
    )
    assert payload == {"second": False, "active": 1}


def test_codex_status_and_doctor_trigger_resource_reap():
    companion = read_text(PLUGIN / "scripts" / "codex-companion.mjs")
    doctor = read_text(PLUGIN / "scripts" / "lib" / "doctor.mjs")
    assert "releaseTerminalJobLeasesForWorkspace(workspaceRoot, process.env)" in companion
    assert "reapStaleResourceLeases(process.env)" in companion
    assert "releaseTerminalJobLeasesForWorkspace(cwd, env)" in doctor
    assert "reapStaleResourceLeases(env)" in doctor


def test_codex_status_reaps_transferred_terminal_job_lease_even_if_pid_looks_alive(tmp_path):
    payload = run_node_script(
        """
        import { upsertJob, writeJobFile } from './plugins/codex/scripts/lib/state.mjs';
        import { acquireResourceLease } from './plugins/codex/scripts/lib/resource-governor.mjs';
        import { releaseTerminalJobLeasesForWorkspace } from './plugins/codex/scripts/lib/terminal-lease-cleanup.mjs';
        const cwd = process.argv[1];
        const job = { id: 'task-test', status: 'completed', phase: 'done', pid: process.pid, logFile: null };
        upsertJob(cwd, job);
        writeJobFile(cwd, job.id, job);
        const first = acquireResourceLease('background-job', { env: process.env, limit: 1, jobId: job.id, pid: process.pid });
        const released = releaseTerminalJobLeasesForWorkspace(cwd, process.env);
        const second = acquireResourceLease('background-job', { env: process.env, limit: 1 });
        second.release();
        console.log(JSON.stringify({ first: first.ok, released, second: second.ok }));
        """,
        env=governor_env(tmp_path),
        args=[str(tmp_path)],
    )
    assert payload == {"first": True, "released": 1, "second": True}


def test_codex_job_lifecycle_classifies_running_suspect_and_lost():
    payload = run_node_script(
        """
        import {
          JOB_LOST_AFTER_MS,
          JOB_SUSPECT_AFTER_MS,
          classifyJobLiveness
        } from './plugins/codex/scripts/lib/job-lifecycle.mjs';

        const nowMs = 1_000_000;
        const alive = () => true;
        const dead = () => false;
        const cases = {
          terminal: classifyJobLiveness({ id: 'done', status: 'completed' }, { nowMs, isProcessAlive: alive }),
          healthy: classifyJobLiveness(
            { id: 'healthy', status: 'running', heartbeatAtMs: nowMs - 1000, pid: process.pid },
            { nowMs, isProcessAlive: alive }
          ),
          suspect: classifyJobLiveness(
            { id: 'suspect', status: 'running', heartbeatAtMs: nowMs - JOB_SUSPECT_AFTER_MS - 1, pid: process.pid },
            { nowMs, isProcessAlive: alive }
          ),
          lost: classifyJobLiveness(
            { id: 'lost', status: 'running', heartbeatAtMs: nowMs - JOB_LOST_AFTER_MS - 1, pid: process.pid },
            { nowMs, isProcessAlive: alive }
          ),
          deadSuspect: classifyJobLiveness(
            { id: 'dead-suspect', status: 'running', heartbeatAtMs: nowMs - 1000, pid: 99999999 },
            { nowMs, isProcessAlive: dead }
          ),
          deadLost: classifyJobLiveness(
            { id: 'dead-lost', status: 'running', heartbeatAtMs: nowMs - JOB_LOST_AFTER_MS - 1, pid: 99999999 },
            { nowMs, isProcessAlive: dead }
          ),
          missingHeartbeat: classifyJobLiveness(
            { id: 'missing', status: 'running', pid: process.pid },
            { nowMs, isProcessAlive: alive }
          )
        };
        console.log(JSON.stringify(cases));
        """
    )

    assert payload["terminal"] == {"state": "terminal", "reason": "completed"}
    assert payload["healthy"]["state"] == "healthy"
    assert payload["healthy"]["reason"] == "heartbeat-current"
    assert payload["suspect"]["state"] == "suspect"
    assert payload["suspect"]["reason"] == "heartbeat-stale"
    assert payload["lost"]["state"] == "lost"
    assert payload["lost"]["reason"] == "heartbeat-lost"
    assert payload["deadSuspect"]["state"] == "suspect"
    assert payload["deadSuspect"]["reason"] == "process-not-alive"
    assert payload["deadLost"]["state"] == "lost"
    assert payload["deadLost"]["reason"] == "process-not-alive"
    assert payload["missingHeartbeat"]["state"] == "lost"
    assert payload["missingHeartbeat"]["reason"] == "heartbeat-lost"


def test_codex_job_lifecycle_uses_updated_at_for_legacy_jobs():
    payload = run_node_script(
        """
        import { JOB_SUSPECT_AFTER_MS, classifyJobLiveness } from './plugins/codex/scripts/lib/job-lifecycle.mjs';
        const nowMs = Date.parse('2026-01-01T00:10:00.000Z');
        const fresh = new Date(nowMs - 1000).toISOString();
        const stale = new Date(nowMs - JOB_SUSPECT_AFTER_MS - 1).toISOString();
        console.log(JSON.stringify({
          fresh: classifyJobLiveness({ id: 'fresh', status: 'running', updatedAt: fresh }, { nowMs }),
          stale: classifyJobLiveness({ id: 'stale', status: 'running', updatedAt: stale }, { nowMs })
        }));
        """
    )

    assert payload["fresh"]["state"] == "healthy"
    assert payload["fresh"]["reason"] == "heartbeat-current"
    assert payload["stale"]["state"] == "suspect"
    assert payload["stale"]["reason"] == "heartbeat-stale"


def test_codex_heartbeat_does_not_rewrite_global_job_state_or_terminal_jobs(tmp_path):
    payload = run_node_script(
        """
        import { writeHeartbeatIfRunning } from './plugins/codex/scripts/lib/tracked-jobs.mjs';
        import { listJobs, readJobFile, resolveJobFile, upsertJob, writeJobFile } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        const running = { id: 'running-heartbeat', status: 'running', workspaceRoot: cwd, heartbeatAtMs: 10, heartbeat: 'old' };
        const terminal = { id: 'terminal-heartbeat', status: 'completed', workspaceRoot: cwd };
        upsertJob(cwd, { ...running, sharedOnly: true });
        writeJobFile(cwd, running.id, running);
        upsertJob(cwd, terminal);
        writeJobFile(cwd, terminal.id, terminal);
        writeHeartbeatIfRunning(running, 123456, () => true);
        writeHeartbeatIfRunning(terminal, 123456, () => true);
        console.log(JSON.stringify({
          sharedRunning: listJobs(cwd).find((job) => job.id === running.id),
          storedRunning: readJobFile(resolveJobFile(cwd, running.id)),
          storedTerminal: readJobFile(resolveJobFile(cwd, terminal.id))
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["sharedRunning"]["heartbeatAtMs"] == 10
    assert payload["sharedRunning"]["heartbeat"] == "old"
    assert payload["sharedRunning"]["sharedOnly"] is True
    assert payload["storedRunning"]["heartbeatAtMs"] == 123456
    assert payload["storedRunning"]["heartbeat"] == "1970-01-01T00:02:03.456Z"
    assert "heartbeatAtMs" not in payload["storedTerminal"]


def test_codex_stop_child_disables_heartbeat_and_progress_updates():
    source = read_text(PLUGIN / "scripts" / "lib" / "tracked-jobs.mjs")
    heartbeat = js_function_body(source, "writeHeartbeatIfRunning")
    progress = js_function_body(source, "createJobProgressUpdater")
    assert 'process.env.CODEX_FOR_CLAUDE_DISABLE_HEARTBEAT === "1"' in heartbeat
    assert 'process.env.CODEX_FOR_CLAUDE_DISABLE_PROGRESS_UPDATES === "1"' in progress


def test_codex_progress_updates_use_locked_job_file_mutation():
    source = read_text(PLUGIN / "scripts" / "lib" / "tracked-jobs.mjs")
    body = js_function_body(source, "createJobProgressUpdater")
    assert "mutateJobFile(workspaceRoot, jobId" in body
    assert "upsertJob(workspaceRoot, patch)" in body
    assert body.index("upsertJob(workspaceRoot, patch)") < body.index("mutateJobFile(workspaceRoot, jobId")
    assert "resolveJobFile(workspaceRoot, jobId)" not in body
    assert "readJobFile(jobFile)" not in body
    assert "writeJobFile(workspaceRoot, jobId" not in body


def test_codex_state_preserves_liveness_fields_through_save_state(tmp_path):
    payload = run_node_script(
        """
        import { listJobs, saveState } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        saveState(cwd, {
          jobs: [{
            id: 'liveness-state',
            status: 'running',
            heartbeatAtMs: 123,
            heartbeat: '1970-01-01T00:00:00.123Z',
            updatedAt: '1970-01-01T00:00:00.123Z'
          }]
        });
        console.log(JSON.stringify({ job: listJobs(cwd)[0] }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["job"]["heartbeatAtMs"] == 123
    assert payload["job"]["heartbeat"] == "1970-01-01T00:00:00.123Z"


def test_codex_session_lifecycle_cleanup_uses_locked_update_state():
    source = read_text(PLUGIN / "scripts" / "session-lifecycle-hook.mjs")
    assert "saveState" not in source
    assert "updateState" in source
    cleanup = js_function_body(source, "cleanupSessionJobs")
    assert "updateState(workspaceRoot" in cleanup
    assert "state.jobs = state.jobs.filter((job) => job.sessionId !== sessionId)" in cleanup


def test_codex_state_lock_order_is_one_way():
    source = read_text(PLUGIN / "scripts" / "lib" / "state.mjs")
    assert "const LOCK_CONTEXT" in source
    assert "LOCK_CONTEXT.stateDepth" in source
    assert "LOCK_CONTEXT.jobDepth" in source
    with_state = js_function_body(source, "withStateLock")
    with_job = js_function_body(source, "withJobFileLock")
    assert "LOCK_CONTEXT.jobDepth" in with_state
    assert "state lock cannot be acquired while holding a job-file lock" in with_state
    assert "LOCK_CONTEXT.jobDepth" in with_job
    assert "job-file lock cannot be nested" in with_job


def test_codex_job_file_lock_enforces_runtime_order(tmp_path):
    payload = run_node_script(
        """
        import { mutateJobFile, updateState, withJobFileLock } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        const nestedJob = (() => {
          try {
            withJobFileLock(cwd, 'job-lock-order', () => mutateJobFile(cwd, 'job-lock-order', (job) => job));
            return null;
          } catch (error) {
            return error.message;
          }
        })();
        const stateInsideJob = (() => {
          try {
            withJobFileLock(cwd, 'job-lock-order', () => updateState(cwd, () => {}));
            return null;
          } catch (error) {
            return error.message;
          }
        })();
        console.log(JSON.stringify({ nestedJob, stateInsideJob }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["nestedJob"] == "job-file lock cannot be nested"
    assert payload["stateInsideJob"] == "state lock cannot be acquired while holding a job-file lock"


def test_codex_progress_upsert_prune_completes_before_job_file_mutation():
    source = read_text(PLUGIN / "scripts" / "lib" / "tracked-jobs.mjs")
    body = js_function_body(source, "createJobProgressUpdater")
    assert body.index("upsertJob(workspaceRoot, patch)") < body.index("mutateJobFile(workspaceRoot, jobId")


def test_codex_status_json_includes_liveness(tmp_path):
    env = companion_env(tmp_path, fake_cli_dir(tmp_path, {"plugins": []}))
    run_node_script(
        """
        import { upsertJob, writeJobFile } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        const job = {
          id: 'json-liveness',
          status: 'running',
          phase: 'running',
          workspaceRoot: cwd,
          updatedAt: new Date().toISOString(),
          heartbeatAtMs: Date.now(),
          heartbeat: new Date().toISOString(),
          pid: null
        };
        upsertJob(cwd, job);
        writeJobFile(cwd, job.id, job);
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )
    result = run_companion(["status", "--cwd", str(tmp_path), "--json", "--all"], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    job = next(item for item in payload["running"] if item["id"] == "json-liveness")
    assert job["liveness"]["state"] == "healthy"
    assert job["liveness"]["reason"] == "heartbeat-current"


def test_codex_status_liveness_reads_per_job_heartbeat(tmp_path):
    env = companion_env(tmp_path, fake_cli_dir(tmp_path, {"plugins": []}))
    run_node_script(
        """
        import { JOB_LOST_AFTER_MS } from './plugins/codex/scripts/lib/job-lifecycle.mjs';
        import { upsertJob, writeJobFile } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        const old = new Date(Date.now() - JOB_LOST_AFTER_MS - 1000).toISOString();
        const shared = {
          id: 'per-job-liveness',
          status: 'running',
          phase: 'running',
          workspaceRoot: cwd,
          updatedAt: old,
          heartbeatAtMs: Date.now() - JOB_LOST_AFTER_MS - 1000,
          heartbeat: old,
          pid: null
        };
        upsertJob(cwd, shared);
        writeJobFile(cwd, shared.id, {
          ...shared,
          heartbeatAtMs: Date.now(),
          heartbeat: new Date().toISOString()
        });
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )
    result = run_companion(["status", "--cwd", str(tmp_path), "--json", "--all"], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    job = next(item for item in payload["running"] if item["id"] == "per-job-liveness")
    assert job["liveness"]["state"] == "healthy"
    assert job["liveness"]["reason"] == "heartbeat-current"


def test_codex_companion_import_is_side_effect_free():
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", "await import('./plugins/codex/scripts/codex-companion.mjs')"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_codex_companion_guarded_entrypoint_copy_tree_doctor_smoke(tmp_path):
    repo = copy_repo(tmp_path)
    bin_dir = fake_cli_dir(tmp_path, {"plugins": []})
    result = subprocess.run(
        [NODE, "plugins/codex/scripts/codex-companion.mjs", "doctor", "--json"],
        cwd=repo,
        env={**os.environ, **companion_env(tmp_path, bin_dir)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["ok"] is True
