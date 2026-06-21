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
    assert 'error?.code === "ESESSIONENDED"' in body
    assert body.index('error?.code === "ESESSIONENDED"') < body.index("if (!transferred)")
    assert "hasEndedSession(queuedRecord.workspaceRoot, queuedRecord.sessionId)" in body
    assert body.index("hasEndedSession(queuedRecord.workspaceRoot, queuedRecord.sessionId)") < body.index("if (!transferred)")
    assert body.count("backgroundLease.release()") == 3


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


def test_codex_background_enqueue_aborts_when_session_ends_after_shared_publish(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import { __testHooks } from './plugins/codex/scripts/codex-companion.mjs';
        import {
          listJobs,
          markSessionEnded,
          resolveJobFile,
          resolveJobLogFile,
          updateState
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'task-ended-session-race',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Codex Task: ended session race',
          summary: 'ended session race',
          write: true,
          sessionId: 'session-ended-race',
          workspaceRoot: cwd
        };
        const request = {
          cwd,
          model: null,
          effort: null,
          prompt: 'ended session race',
          write: true,
          resumeLast: false,
          jobId: job.id
        };
        const lease = {
          disabled: false,
          lease: { id: 'background-job-ended-session-race' },
          released: false,
          release() {
            this.released = true;
          }
        };
        let spawnCalled = false;
        let errorCode = null;
        let errorMessage = null;
        try {
          __testHooks.enqueueBackgroundTask(cwd, job, request, lease, {
            afterQueuedStatePublished() {
              updateState(cwd, (state) => {
                markSessionEnded(state, 'session-ended-race');
                state.jobs = state.jobs.filter((item) => item.sessionId !== 'session-ended-race');
              });
            },
            spawnTaskWorker() {
              spawnCalled = true;
              return { pid: 12345 };
            },
            transferResourceLease() {
              return true;
            }
          });
        } catch (error) {
          errorCode = error.code ?? null;
          errorMessage = error.message;
        }
        const jobFile = resolveJobFile(cwd, job.id);
        const logFile = resolveJobLogFile(cwd, job.id);
        console.log(JSON.stringify({
          errorCode,
          errorMessage,
          released: lease.released,
          spawnCalled,
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(logFile)
        }));
        """,
        env=governor_env(tmp_path),
        args=[str(tmp_path)],
    )

    assert payload["errorCode"] == "ESESSIONENDED"
    assert "ended before background task" in payload["errorMessage"]
    assert payload["released"] is True
    assert payload["spawnCalled"] is False
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert payload["logFileExists"] is False


def test_codex_background_enqueue_failure_after_session_end_does_not_write_failed_sidecar(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import { __testHooks } from './plugins/codex/scripts/codex-companion.mjs';
        import {
          listJobs,
          markSessionEnded,
          resolveJobFile,
          resolveJobLogFile,
          updateState
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'task-ended-session-failure',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Codex Task: ended session failure',
          summary: 'ended session failure',
          write: true,
          sessionId: 'session-ended-failure',
          workspaceRoot: cwd
        };
        const request = {
          cwd,
          model: null,
          effort: null,
          prompt: 'ended session failure secret',
          write: true,
          resumeLast: false,
          jobId: job.id
        };
        const lease = {
          disabled: false,
          lease: { id: 'background-job-ended-session-failure' },
          released: false,
          release() {
            this.released = true;
          }
        };
        let errorCode = null;
        let errorMessage = null;
        try {
          __testHooks.enqueueBackgroundTask(cwd, job, request, lease, {
            spawnTaskWorker() {
              updateState(cwd, (state) => {
                markSessionEnded(state, 'session-ended-failure');
                state.jobs = state.jobs.filter((item) => item.sessionId !== 'session-ended-failure');
              });
              throw new Error('spawn failed after session end');
            },
            transferResourceLease() {
              return true;
            }
          });
        } catch (error) {
          errorCode = error.code ?? null;
          errorMessage = error.message;
        }
        const jobFile = resolveJobFile(cwd, job.id);
        const logFile = resolveJobLogFile(cwd, job.id);
        console.log(JSON.stringify({
          errorCode,
          errorMessage,
          released: lease.released,
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          jobFileText: fs.existsSync(jobFile) ? fs.readFileSync(jobFile, 'utf8') : '',
          logFileExists: fs.existsSync(logFile)
        }));
        """,
        env=governor_env(tmp_path),
        args=[str(tmp_path)],
    )

    assert payload["errorCode"] == "ESESSIONENDED"
    assert "ended before background task" in payload["errorMessage"]
    assert payload["released"] is True
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert "ended session failure secret" not in payload["jobFileText"]
    assert payload["logFileExists"] is False


def test_codex_background_enqueue_consumes_queued_sidecar_rejection(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import { __testHooks } from './plugins/codex/scripts/codex-companion.mjs';
        import {
          listJobs,
          markSessionEnded,
          resolveJobFile,
          resolveJobLogFile,
          updateState
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'task-queued-sidecar-rejected',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Codex Task: queued sidecar rejected',
          summary: 'queued sidecar rejected',
          write: true,
          sessionId: 'session-queued-sidecar-rejected',
          workspaceRoot: cwd
        };
        const request = {
          cwd,
          model: null,
          effort: null,
          prompt: 'queued sidecar rejected secret',
          write: true,
          resumeLast: false,
          jobId: job.id
        };
        const lease = {
          disabled: false,
          lease: { id: 'background-job-queued-sidecar-rejected' },
          released: false,
          release() {
            this.released = true;
          }
        };
        let spawnCalled = false;
        let errorCode = null;
        let errorMessage = null;
        try {
          __testHooks.enqueueBackgroundTask(cwd, job, request, lease, {
            beforeQueuedJobFileWrite() {
              updateState(cwd, (state) => {
                markSessionEnded(state, 'session-queued-sidecar-rejected');
                state.jobs = state.jobs.filter((item) => item.sessionId !== 'session-queued-sidecar-rejected');
              });
            },
            spawnTaskWorker() {
              spawnCalled = true;
              return { pid: 12345 };
            },
            transferResourceLease() {
              return true;
            }
          });
        } catch (error) {
          errorCode = error.code ?? null;
          errorMessage = error.message;
        }
        const jobFile = resolveJobFile(cwd, job.id);
        const logFile = resolveJobLogFile(cwd, job.id);
        console.log(JSON.stringify({
          errorCode,
          errorMessage,
          released: lease.released,
          spawnCalled,
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(logFile)
        }));
        """,
        env=governor_env(tmp_path),
        args=[str(tmp_path)],
    )

    assert payload["errorCode"] == "ESESSIONENDED"
    assert "ended before background task" in payload["errorMessage"]
    assert payload["released"] is True
    assert payload["spawnCalled"] is False
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert payload["logFileExists"] is False


def test_codex_background_enqueue_consumes_spawned_sidecar_rejection(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import { __testHooks } from './plugins/codex/scripts/codex-companion.mjs';
        import {
          listJobs,
          markSessionEnded,
          resolveJobFile,
          resolveJobLogFile,
          updateState
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'task-spawned-sidecar-rejected',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Codex Task: spawned sidecar rejected',
          summary: 'spawned sidecar rejected',
          write: true,
          sessionId: 'session-spawned-sidecar-rejected',
          workspaceRoot: cwd
        };
        const request = {
          cwd,
          model: null,
          effort: null,
          prompt: 'spawned sidecar rejected secret',
          write: true,
          resumeLast: false,
          jobId: job.id
        };
        const lease = {
          disabled: false,
          lease: { id: 'background-job-spawned-sidecar-rejected' },
          released: false,
          release() {
            this.released = true;
          }
        };
        let transferCalled = false;
        let errorCode = null;
        let errorMessage = null;
        try {
          __testHooks.enqueueBackgroundTask(cwd, job, request, lease, {
            spawnTaskWorker() {
              return { pid: 99999999 };
            },
            transferResourceLease() {
              transferCalled = true;
              return true;
            },
            beforeSpawnedJobFileWrite() {
              updateState(cwd, (state) => {
                markSessionEnded(state, 'session-spawned-sidecar-rejected');
                state.jobs = state.jobs.filter((item) => item.sessionId !== 'session-spawned-sidecar-rejected');
              });
            }
          });
        } catch (error) {
          errorCode = error.code ?? null;
          errorMessage = error.message;
        }
        const jobFile = resolveJobFile(cwd, job.id);
        const logFile = resolveJobLogFile(cwd, job.id);
        console.log(JSON.stringify({
          errorCode,
          errorMessage,
          released: lease.released,
          transferCalled,
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          jobFileText: fs.existsSync(jobFile) ? fs.readFileSync(jobFile, 'utf8') : '',
          logFileExists: fs.existsSync(logFile)
        }));
        """,
        env=governor_env(tmp_path),
        args=[str(tmp_path)],
    )

    assert payload["errorCode"] == "ESESSIONENDED"
    assert "ended before background task" in payload["errorMessage"]
    assert payload["released"] is True
    assert payload["transferCalled"] is True
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert "spawned sidecar rejected secret" not in payload["jobFileText"]
    assert payload["logFileExists"] is False


def test_codex_background_launch_failure_consumes_failed_sidecar_rejection(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import { __testHooks } from './plugins/codex/scripts/codex-companion.mjs';
        import {
          listJobs,
          markSessionEnded,
          resolveJobFile,
          resolveJobLogFile,
          updateState
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'task-failed-sidecar-rejected',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Codex Task: failed sidecar rejected',
          summary: 'failed sidecar rejected',
          write: true,
          sessionId: 'session-failed-sidecar-rejected',
          workspaceRoot: cwd
        };
        const request = {
          cwd,
          model: null,
          effort: null,
          prompt: 'failed sidecar rejected secret',
          write: true,
          resumeLast: false,
          jobId: job.id
        };
        const lease = {
          disabled: false,
          lease: { id: 'background-job-failed-sidecar-rejected' },
          released: false,
          release() {
            this.released = true;
          }
        };
        let errorCode = null;
        let errorMessage = null;
        try {
          __testHooks.enqueueBackgroundTask(cwd, job, request, lease, {
            spawnTaskWorker() {
              throw new Error('spawn failed before failed sidecar');
            },
            transferResourceLease() {
              return true;
            },
            beforeFailedJobFileWrite() {
              updateState(cwd, (state) => {
                markSessionEnded(state, 'session-failed-sidecar-rejected');
                state.jobs = state.jobs.filter((item) => item.sessionId !== 'session-failed-sidecar-rejected');
              });
            }
          });
        } catch (error) {
          errorCode = error.code ?? null;
          errorMessage = error.message;
        }
        const jobFile = resolveJobFile(cwd, job.id);
        const logFile = resolveJobLogFile(cwd, job.id);
        console.log(JSON.stringify({
          errorCode,
          errorMessage,
          released: lease.released,
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          jobFileText: fs.existsSync(jobFile) ? fs.readFileSync(jobFile, 'utf8') : '',
          logFileExists: fs.existsSync(logFile)
        }));
        """,
        env=governor_env(tmp_path),
        args=[str(tmp_path)],
    )

    assert payload["errorCode"] == "ESESSIONENDED"
    assert "ended before background task" in payload["errorMessage"]
    assert payload["released"] is True
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert "failed sidecar rejected secret" not in payload["jobFileText"]
    assert payload["logFileExists"] is False


def test_codex_cancel_after_session_end_does_not_write_cancelled_sidecar(tmp_path):
    env = governor_env(tmp_path)
    run_node_script(
        """
        import fs from 'node:fs';
        import {
          markSessionEnded,
          resolveJobLogFile,
          updateState,
          upsertJob,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'cancel-ended-session',
          status: 'running',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Cancel ended session',
          workspaceRoot: cwd,
          sessionId: 'session-cancel-ended',
          pid: 99999999,
          logFile: resolveJobLogFile(cwd, 'cancel-ended-session'),
          request: { secret: 'cancel secret' },
          updatedAt: new Date().toISOString()
        };
        upsertJob(cwd, job);
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, 'cancel log\\n', 'utf8');
        updateState(cwd, (state) => {
          markSessionEnded(state, 'session-cancel-ended');
        });
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    result = run_companion(
        ["cancel", "cancel-ended-session", "--cwd", str(tmp_path), "--json"],
        cwd=tmp_path,
        env=env,
    )
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          listJobs,
          resolveJobFile,
          resolveJobLogFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const jobFile = resolveJobFile(cwd, 'cancel-ended-session');
        const logFile = resolveJobLogFile(cwd, 'cancel-ended-session');
        console.log(JSON.stringify({
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          jobFileText: fs.existsSync(jobFile) ? fs.readFileSync(jobFile, 'utf8') : '',
          logFileExists: fs.existsSync(logFile)
        }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    assert result.returncode != 0
    assert 'No job found for "cancel-ended-session"' in result.stderr
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert "cancel secret" not in payload["jobFileText"]
    assert payload["logFileExists"] is False


def test_codex_cancel_ignores_tombstoned_sidecar_only_active_job(tmp_path):
    env = governor_env(tmp_path)
    run_node_script(
        """
        import fs from 'node:fs';
        import {
          markSessionEnded,
          resolveJobLogFile,
          updateState,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        process.env.CODEX_FOR_CLAUDE_SKIP_STATE_PRUNE = '1';
        const job = {
          id: 'cancel-tombstoned-sidecar-only',
          status: 'running',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Cancel tombstoned sidecar only',
          workspaceRoot: cwd,
          sessionId: 'session-cancel-tombstoned-sidecar',
          pid: 99999999,
          request: { secret: 'cancel tombstoned secret' },
          logFile: resolveJobLogFile(cwd, 'cancel-tombstoned-sidecar-only'),
          updatedAt: new Date().toISOString()
        };
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, 'cancel tombstoned log\\n', 'utf8');
        updateState(cwd, (state) => {
          markSessionEnded(state, 'session-cancel-tombstoned-sidecar');
          state.jobs = state.jobs.filter((item) => item.id !== job.id);
        });
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    result = run_companion(
        ["cancel", "cancel-tombstoned-sidecar-only", "--cwd", str(tmp_path), "--json"],
        cwd=tmp_path,
        env=env,
    )

    assert result.returncode != 0
    assert 'No job found for "cancel-tombstoned-sidecar-only"' in result.stderr


def test_codex_cancel_rejects_when_session_ends_before_cancel_sidecar_write(tmp_path):
    env = governor_env(tmp_path)
    script = f"""
        import fs from 'node:fs';

        const cwd = process.argv[1];
        const originalRenameSync = fs.renameSync;
        let injected = false;
        fs.renameSync = function patchedRenameSync(from, to) {{
          originalRenameSync.call(this, from, to);
          if (injected || !String(to).endsWith('/state.json')) {{
            return;
          }}
          try {{
            const state = JSON.parse(fs.readFileSync(to, 'utf8'));
            const hasCancelled = state.jobs?.some((job) => job.id === 'cancel-write-race' && job.status === 'cancelled');
            if (!hasCancelled) {{
              return;
            }}
            injected = true;
            state.endedSessions = [...(state.endedSessions || []), 'session-cancel-write-race'];
            state.jobs = state.jobs.filter((job) => job.id !== 'cancel-write-race');
            fs.writeFileSync(to, `${{JSON.stringify(state, null, 2)}}\\n`, 'utf8');
          }} catch {{
            // Non-target state writes are irrelevant for this race injection.
          }}
        }};

        const state = await import('./plugins/codex/scripts/lib/state.mjs');
        const companion = await import('./plugins/codex/scripts/codex-companion.mjs');
        const job = {{
          id: 'cancel-write-race',
          status: 'running',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Cancel write race',
          workspaceRoot: cwd,
          sessionId: 'session-cancel-write-race',
          pid: 99999999,
          logFile: state.resolveJobLogFile(cwd, 'cancel-write-race'),
          request: {{ secret: 'cancel write race secret' }},
          updatedAt: new Date().toISOString()
        }};
        state.upsertJob(cwd, job);
        state.writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, 'cancel write race log\\n', 'utf8');
        const originalStdoutWrite = process.stdout.write.bind(process.stdout);
        let capturedStdout = '';
        process.stdout.write = (chunk, ...args) => {{
          capturedStdout += String(chunk);
          return true;
        }};
        let errorMessage = '';
        try {{
          await companion.__testHooks.handleCancel(['cancel-write-race', '--cwd', cwd, '--json']);
        }} catch (error) {{
          errorMessage = error instanceof Error ? error.message : String(error);
        }} finally {{
          process.stdout.write = originalStdoutWrite;
        }}
        const jobFile = state.resolveJobFile(cwd, job.id);
        console.log(JSON.stringify({{
          injected,
          capturedStdout,
          errorMessage,
          jobs: state.listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(job.logFile)
        }}));
    """
    payload = run_node_script(script, env=env, args=[str(tmp_path)])

    assert payload["injected"] is True
    assert payload["capturedStdout"] == ""
    assert "ended before job cancel-write-race could be cancelled" in payload["errorMessage"]
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert payload["logFileExists"] is False


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
          ),
          heartbeatStringIgnored: classifyJobLiveness(
            { id: 'legacy-heartbeat-field', status: 'running', heartbeat: new Date(nowMs - 1000).toISOString(), pid: process.pid },
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
    assert payload["heartbeatStringIgnored"]["state"] == "lost"
    assert payload["heartbeatStringIgnored"]["reason"] == "heartbeat-lost"


def test_codex_job_lifecycle_uses_updated_at_for_legacy_jobs():
    payload = run_node_script(
        """
        import { JOB_SUSPECT_AFTER_MS, classifyJobLiveness } from './plugins/codex/scripts/lib/job-lifecycle.mjs';
        const nowMs = Date.parse('2026-01-01T00:10:00.000Z');
        const fresh = new Date(nowMs - 1000).toISOString();
        const stale = new Date(nowMs - JOB_SUSPECT_AFTER_MS - 1).toISOString();
        console.log(JSON.stringify({
          fresh: classifyJobLiveness({ id: 'fresh', status: 'running', updatedAt: fresh }, { nowMs }),
          stale: classifyJobLiveness({ id: 'stale', status: 'running', updatedAt: stale }, { nowMs }),
          updatedAtBeatsHeartbeatField: classifyJobLiveness({
            id: 'updated-at-source',
            status: 'running',
            updatedAt: fresh,
            heartbeat: stale
          }, { nowMs })
        }));
        """
    )

    assert payload["fresh"]["state"] == "healthy"
    assert payload["fresh"]["reason"] == "heartbeat-current"
    assert payload["stale"]["state"] == "suspect"
    assert payload["stale"]["reason"] == "heartbeat-stale"
    assert payload["updatedAtBeatsHeartbeatField"]["state"] == "healthy"
    assert payload["updatedAtBeatsHeartbeatField"]["reason"] == "heartbeat-current"


def test_codex_heartbeat_does_not_rewrite_global_job_state_or_terminal_jobs(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import { writeHeartbeatIfRunning } from './plugins/codex/scripts/lib/tracked-jobs.mjs';
        import { listJobs, readJobFile, resolveJobFile, upsertJob, writeJobFile } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        const running = { id: 'running-heartbeat', status: 'running', workspaceRoot: cwd, heartbeatAtMs: 10, heartbeat: 'old' };
        const terminal = { id: 'terminal-heartbeat', status: 'completed', workspaceRoot: cwd };
        upsertJob(cwd, { ...running, sharedOnly: true });
        writeJobFile(cwd, running.id, running);
        upsertJob(cwd, terminal);
        writeJobFile(cwd, terminal.id, terminal);
        const terminalFile = resolveJobFile(cwd, terminal.id);
        const terminalMtimeBefore = fs.statSync(terminalFile).mtimeMs;
        const runningResult = writeHeartbeatIfRunning(running, 123456, () => true);
        const terminalResult = writeHeartbeatIfRunning({ ...running, id: terminal.id }, 123456, () => true);
        const terminalMtimeAfter = fs.statSync(terminalFile).mtimeMs;
        console.log(JSON.stringify({
          sharedRunning: listJobs(cwd).find((job) => job.id === running.id),
          storedRunning: readJobFile(resolveJobFile(cwd, running.id)),
          storedTerminal: readJobFile(terminalFile),
          runningResult,
          terminalResult,
          terminalMtimeUnchanged: terminalMtimeAfter === terminalMtimeBefore
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["sharedRunning"]["heartbeatAtMs"] == 10
    assert payload["sharedRunning"]["heartbeat"] == "old"
    assert payload["sharedRunning"]["sharedOnly"] is True
    assert payload["storedRunning"]["heartbeatAtMs"] == 123456
    assert payload["storedRunning"]["heartbeatAt"] == "1970-01-01T00:02:03.456Z"
    assert payload["storedRunning"]["heartbeat"] == "old"
    assert payload["runningResult"] is True
    assert payload["terminalResult"] is False
    assert payload["terminalMtimeUnchanged"] is True
    assert "heartbeatAtMs" not in payload["storedTerminal"]


def test_codex_heartbeat_after_session_end_removes_sidecar_without_republish(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          writeHeartbeatIfRunning
        } from './plugins/codex/scripts/lib/tracked-jobs.mjs';
        import {
          listJobs,
          markSessionEnded,
          resolveJobFile,
          resolveJobLogFile,
          updateState,
          upsertJob,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'heartbeat-ended-session',
          status: 'running',
          workspaceRoot: cwd,
          sessionId: 'session-ended-heartbeat',
          request: { secret: 'heartbeat secret' },
          logFile: resolveJobLogFile(cwd, 'heartbeat-ended-session'),
          updatedAt: new Date().toISOString()
        };
        upsertJob(cwd, job);
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, 'heartbeat secret log\\n', 'utf8');
        updateState(cwd, (state) => {
          markSessionEnded(state, 'session-ended-heartbeat');
          state.jobs = state.jobs.filter((item) => item.sessionId !== 'session-ended-heartbeat');
        });
        const result = writeHeartbeatIfRunning(job, 123456, () => true);
        const jobFile = resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          result,
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          jobFileText: fs.existsSync(jobFile) ? fs.readFileSync(jobFile, 'utf8') : '',
          logFileExists: fs.existsSync(job.logFile)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["result"] is False
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert "heartbeat secret" not in payload["jobFileText"]
    assert payload["logFileExists"] is False


def test_codex_stop_child_disables_heartbeat_and_progress_updates():
    source = read_text(PLUGIN / "scripts" / "lib" / "tracked-jobs.mjs")
    heartbeat = js_function_body(source, "writeHeartbeatIfRunning")
    progress = js_function_body(source, "createJobProgressUpdater")
    run_tracked = js_function_body(source, "runTrackedJob")
    assert 'process.env.CODEX_FOR_CLAUDE_DISABLE_HEARTBEAT === "1"' in heartbeat
    assert 'process.env.CODEX_FOR_CLAUDE_DISABLE_PROGRESS_UPDATES === "1"' in progress
    assert "let heartbeatActive = true" in run_tracked
    assert "let heartbeat = null" in run_tracked
    assert "heartbeat?.unref?.()" in run_tracked
    assert run_tracked.count("writeJobFile(job.workspaceRoot, job.id") == 3
    assert run_tracked.count("heartbeatActive = false") >= 2
    assert run_tracked.index("upsertJob(job.workspaceRoot, runningRecord)") < run_tracked.index("writeJobFile(job.workspaceRoot, job.id, runningRecord)")
    assert "if (!upsertJob(job.workspaceRoot, runningRecord))" in run_tracked
    assert run_tracked.index("heartbeatActive = false") < run_tracked.index("writeJobFile(job.workspaceRoot, job.id", run_tracked.index("const execution = await runner()"))
    assert run_tracked.index("upsertJob(job.workspaceRoot, {", run_tracked.index("const execution = await runner()")) < run_tracked.index("writeJobFile(job.workspaceRoot, job.id", run_tracked.index("const execution = await runner()"))
    assert "const completedJobFile = writeJobFile(job.workspaceRoot, job.id" in run_tracked
    assert run_tracked.index("if (completedJobFile)") < run_tracked.index("appendLogBlockIfJobCurrent(")
    catch_index = run_tracked.index("} catch (error) {")
    assert run_tracked.index("heartbeatActive = false", catch_index) < run_tracked.index("readStoredJobOrNull", catch_index)
    assert run_tracked.index("upsertJob(job.workspaceRoot, {", catch_index) < run_tracked.index("writeJobFile(job.workspaceRoot, job.id", catch_index)
    assert run_tracked.index("readStoredJobOrNull", catch_index) < run_tracked.index("writeJobFile(job.workspaceRoot, job.id", catch_index)


def test_codex_progress_updates_use_locked_job_file_mutation():
    source = read_text(PLUGIN / "scripts" / "lib" / "tracked-jobs.mjs")
    body = js_function_body(source, "createJobProgressUpdater")
    assert "mutateJobFile(workspaceRoot, jobId" in body
    assert "upsertJob(workspaceRoot, patch)" in body
    assert "upsertJob(workspaceRoot, sharedProgressJobPatch(updated))" in body
    assert body.index("mutateJobFile(workspaceRoot, jobId") < body.index("readJobFile(resolveJobFile(workspaceRoot, jobId))")
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


def test_codex_state_upsert_rejects_ended_session_jobs(tmp_path):
    payload = run_node_script(
        """
        import {
          listJobs,
          markSessionEnded,
          updateState,
          upsertJob
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        upsertJob(cwd, {
          id: 'existing-ended-session',
          status: 'running',
          sessionId: 'session-upsert-ended',
          workspaceRoot: cwd
        });
        updateState(cwd, (state) => {
          markSessionEnded(state, 'session-upsert-ended');
        });
        const minimalApplied = upsertJob(cwd, {
          id: 'existing-ended-session',
          phase: 'running'
        });
        const directApplied = upsertJob(cwd, {
          id: 'direct-ended-session',
          status: 'running',
          sessionId: 'session-upsert-ended',
          workspaceRoot: cwd
        });

        console.log(JSON.stringify({
          minimalApplied,
          directApplied,
          jobs: listJobs(cwd)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["minimalApplied"] is False
    assert payload["directApplied"] is False
    assert payload["jobs"] == []


def test_codex_state_write_job_file_rejects_ended_session_sidecars(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          markSessionEnded,
          resolveJobFile,
          resolveJobLogFile,
          updateState,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'write-ended-session',
          status: 'running',
          sessionId: 'session-write-ended',
          workspaceRoot: cwd,
          request: { secret: 'write secret' },
          logFile: resolveJobLogFile(cwd, 'write-ended-session')
        };
        fs.writeFileSync(job.logFile, 'write log\\n', 'utf8');
        updateState(cwd, (state) => {
          markSessionEnded(state, 'session-write-ended');
        });
        const writeResult = writeJobFile(cwd, job.id, job);
        const jobFile = resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          writeResult,
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(job.logFile)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload == {
        "writeResult": None,
        "jobFileExists": False,
        "logFileExists": False,
    }


def test_codex_state_write_job_file_rejects_ended_session_and_removes_existing_log(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          markSessionEnded,
          resolveJobFile,
          resolveJobLogFile,
          updateState,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const oldLog = resolveJobLogFile(cwd, 'write-ended-session-old-log');
        const newLog = resolveJobLogFile(cwd, 'write-ended-session-new-log');
        const oldJob = {
          id: 'write-ended-session-log-mismatch',
          status: 'running',
          sessionId: 'session-write-ended-log-mismatch',
          workspaceRoot: cwd,
          request: { secret: 'old write secret' },
          logFile: oldLog
        };
        const newJob = {
          ...oldJob,
          request: { secret: 'new write secret' },
          logFile: newLog
        };
        writeJobFile(cwd, oldJob.id, oldJob);
        fs.writeFileSync(oldLog, 'OLD_SIDECAR_SECRET\\n', 'utf8');
        fs.writeFileSync(newLog, 'NEW_PAYLOAD_SECRET\\n', 'utf8');
        updateState(cwd, (state) => {
          markSessionEnded(state, 'session-write-ended-log-mismatch');
        });
        const writeResult = writeJobFile(cwd, newJob.id, newJob);
        const jobFile = resolveJobFile(cwd, oldJob.id);

        console.log(JSON.stringify({
          writeResult,
          jobFileExists: fs.existsSync(jobFile),
          oldLogExists: fs.existsSync(oldLog),
          newLogExists: fs.existsSync(newLog),
          oldLogText: fs.existsSync(oldLog) ? fs.readFileSync(oldLog, 'utf8') : '',
          newLogText: fs.existsSync(newLog) ? fs.readFileSync(newLog, 'utf8') : ''
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["writeResult"] is None
    assert payload["jobFileExists"] is False
    assert payload["oldLogExists"] is False
    assert payload["newLogExists"] is False
    assert "OLD_SIDECAR_SECRET" not in payload["oldLogText"]
    assert "NEW_PAYLOAD_SECRET" not in payload["newLogText"]


def test_codex_state_uses_required_slice_contracts():
    source = read_text(PLUGIN / "scripts" / "lib" / "state.mjs")
    save_state = js_function_body(source, "saveState")
    update_state = js_function_body(source, "updateState")
    assert "let previousJobs = []" in save_state
    assert "previousJobs = uniqueJobsById([...loadState(cwd).jobs, ...listJobSidecars(cwd)])" in save_state
    assert save_state.index("previousJobs = uniqueJobsById") < save_state.index("saveStateUnlocked(cwd, state, previousJobs)")
    assert "function uniqueJobsById" in source
    assert "const current = loadState(cwd)" in update_state
    assert "const previousJobs = current.jobs.slice()" in update_state
    assert "mutator(current)" in update_state
    assert "saveStateUnlocked(cwd, current, previousJobs)" in update_state
    assert "const next = mutator(current)" not in update_state
    assert "state.jobs =" not in update_state


def test_codex_state_pruned_job_files_are_removed_under_job_file_lock():
    source = read_text(PLUGIN / "scripts" / "lib" / "state.mjs")
    prune_body = js_function_body(source, "removePrunedJobFiles")
    save_state = js_function_body(source, "saveState")
    update_state = js_function_body(source, "updateState")
    save_unlocked = js_function_body(source, "saveStateUnlocked")
    assert "withJobFileLock(cwd, job.id" in prune_body
    assert "withStateLock" not in prune_body
    assert "saveState(" not in prune_body
    assert "updateState(" not in prune_body
    assert "loadState(cwd)" in prune_body
    assert "const jobFile = resolveJobFile(cwd, job.id)" in prune_body
    assert "removeJobFile(jobFile)" in prune_body
    assert 'storedJob?.status === "queued" || storedJob?.status === "running"' in prune_body
    assert "removeFileIfExists(job.logFile)" in prune_body
    assert save_state.index("withStateLock(cwd") < save_state.index("removePrunedJobFiles(cwd")
    assert update_state.index("withStateLock(cwd") < update_state.index("removePrunedJobFiles(cwd")
    assert re.search(
        r"let previousJobs = \[\];\s*"
        r"const nextState = withStateLock\(cwd, \(\) => \{\s*"
        r"previousJobs = uniqueJobsById\(\[\.\.\.loadState\(cwd\)\.jobs, \.\.\.listJobSidecars\(cwd\)\]\);\s*"
        r"return saveStateUnlocked\(cwd, state, previousJobs\);\s*"
        r"\}\);\s*"
        r"removePrunedJobFiles\(cwd, previousJobs, nextState\.jobs\);",
        save_state,
    )
    assert re.search(
        r"return nextState;\s*"
        r"\}\);\s*"
        r"if \(options\.pruneJobFiles !== false\) \{\s*"
        r"removePrunedJobFiles\(cwd, prunedPreviousJobs, nextState\.jobs\);",
        update_state,
    )
    assert "pruneJobFiles: false" in read_text(PLUGIN / "scripts" / "lib" / "tracked-jobs.mjs")
    assert "withJobFileLock" not in save_unlocked
    assert "removePrunedJobFiles" not in save_unlocked
    assert "removeJobFile" not in save_unlocked


def test_codex_save_state_replacement_removes_omitted_terminal_sidecars(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          resolveJobFile,
          resolveJobLogFile,
          saveState,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'save-state-removed-terminal',
          status: 'completed',
          workspaceRoot: cwd,
          logFile: resolveJobLogFile(cwd, 'save-state-removed-terminal'),
          updatedAt: new Date().toISOString()
        };
        saveState(cwd, { jobs: [job] });
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, 'secret-log\\n', 'utf8');
        saveState(cwd, { jobs: [] });
        const jobFile = resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(job.logFile),
          logFileText: fs.existsSync(job.logFile) ? fs.readFileSync(job.logFile, 'utf8') : ''
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["jobFileExists"] is False
    assert payload["logFileExists"] is False
    assert "secret-log" not in payload["logFileText"]


def test_codex_save_state_preserves_ended_session_tombstones(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          hasEndedSession,
          markSessionEnded,
          resolveJobFile,
          saveState,
          updateState,
          upsertJob,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        updateState(cwd, (state) => {
          markSessionEnded(state, 'session-save-state-ended');
        });
        const endedBefore = hasEndedSession(cwd, 'session-save-state-ended');
        saveState(cwd, { jobs: [] });
        const endedAfterSave = hasEndedSession(cwd, 'session-save-state-ended');
        const job = {
          id: 'save-state-ended-session-job',
          status: 'running',
          workspaceRoot: cwd,
          sessionId: 'session-save-state-ended',
          updatedAt: new Date().toISOString()
        };
        const upserted = upsertJob(cwd, job);
        const writeResult = writeJobFile(cwd, job.id, job);
        const jobFile = resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          endedBefore,
          endedAfterSave,
          upserted,
          writeResult: Boolean(writeResult),
          jobFileExists: fs.existsSync(jobFile)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload == {
        "endedBefore": True,
        "endedAfterSave": True,
        "upserted": False,
        "writeResult": False,
        "jobFileExists": False,
    }


def test_codex_save_state_replacement_filters_ended_session_jobs_from_status(tmp_path):
    env = companion_env(tmp_path, fake_cli_dir(tmp_path, {"plugins": []}))
    payload = run_node_script(
        """
        import {
          listJobs,
          markSessionEnded,
          saveState,
          updateState
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        updateState(cwd, (state) => {
          markSessionEnded(state, 'session-save-state-status-ended');
        });
        saveState(cwd, {
          jobs: [{
            id: 'save-state-status-ended-job',
            status: 'running',
            phase: 'running',
            workspaceRoot: cwd,
            sessionId: 'session-save-state-status-ended',
            updatedAt: new Date().toISOString()
          }]
        });

        console.log(JSON.stringify({
          jobs: listJobs(cwd)
        }));
        """,
        env=env,
        args=[str(tmp_path)],
    )
    result = run_companion(["status", "--cwd", str(tmp_path), "--json", "--all"], cwd=tmp_path, env=env)

    assert payload["jobs"] == []
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["running"] == []
    assert status["latestFinished"] is None
    assert status["recent"] == []


def test_codex_save_state_replacement_filters_ended_session_jobs_using_previous_metadata(tmp_path):
    env = companion_env(tmp_path, fake_cli_dir(tmp_path, {"plugins": []}))
    payload = run_node_script(
        """
        import {
          listJobs,
          markSessionEnded,
          resolveJobLogFile,
          saveState,
          updateState,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const previous = {
          id: 'save-state-previous-session-ended-job',
          status: 'running',
          phase: 'running',
          workspaceRoot: cwd,
          sessionId: 'session-save-state-previous-ended',
          logFile: resolveJobLogFile(cwd, 'save-state-previous-session-ended-job'),
          updatedAt: new Date().toISOString()
        };
        saveState(cwd, { jobs: [previous] });
        writeJobFile(cwd, previous.id, previous);
        saveState(cwd, {
          endedSessions: ['session-save-state-previous-ended'],
          jobs: [{
            id: previous.id,
            status: 'running',
            phase: 'running',
            workspaceRoot: cwd,
            updatedAt: new Date().toISOString()
          }]
        });

        console.log(JSON.stringify({
          jobs: listJobs(cwd)
        }));
        """,
        env=env,
        args=[str(tmp_path)],
    )
    result = run_companion(["status", "--cwd", str(tmp_path), "--json", "--all"], cwd=tmp_path, env=env)

    assert payload["jobs"] == []
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["running"] == []
    assert status["latestFinished"] is None
    assert status["recent"] == []


def test_codex_save_state_replacement_uses_sidecar_session_when_shared_metadata_omits_it(tmp_path):
    env = companion_env(tmp_path, fake_cli_dir(tmp_path, {"plugins": []}))
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          listJobs,
          resolveJobFile,
          resolveJobLogFile,
          saveState,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const id = 'save-state-sidecar-session-ended-job';
        const logFile = resolveJobLogFile(cwd, id);
        const sharedWithoutSession = {
          id,
          status: 'running',
          phase: 'running',
          workspaceRoot: cwd,
          updatedAt: new Date().toISOString()
        };
        const sidecarWithSession = {
          ...sharedWithoutSession,
          sessionId: 'session-save-state-sidecar-ended',
          request: { secret: 'sidecar session secret' },
          logFile
        };
        saveState(cwd, { jobs: [sharedWithoutSession] });
        writeJobFile(cwd, id, sidecarWithSession);
        fs.writeFileSync(logFile, 'SIDECAR_SESSION_LOG_SECRET\\n', 'utf8');
        saveState(cwd, {
          endedSessions: ['session-save-state-sidecar-ended'],
          jobs: [{
            ...sharedWithoutSession,
            updatedAt: new Date().toISOString()
          }]
        });
        const jobFile = resolveJobFile(cwd, id);

        console.log(JSON.stringify({
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          jobFileText: fs.existsSync(jobFile) ? fs.readFileSync(jobFile, 'utf8') : '',
          logFileExists: fs.existsSync(logFile),
          logFileText: fs.existsSync(logFile) ? fs.readFileSync(logFile, 'utf8') : ''
        }));
        """,
        env=env,
        args=[str(tmp_path)],
    )
    result = run_companion(["status", "--cwd", str(tmp_path), "--json", "--all"], cwd=tmp_path, env=env)

    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert "sidecar session secret" not in payload["jobFileText"]
    assert payload["logFileExists"] is False
    assert "SIDECAR_SESSION_LOG_SECRET" not in payload["logFileText"]
    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["running"] == []
    assert status["latestFinished"] is None
    assert status["recent"] == []


def test_codex_save_state_replacement_removes_tombstoned_active_sidecar_log(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          markSessionEnded,
          resolveJobFile,
          resolveJobLogFile,
          saveState,
          updateState,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'save-state-tombstoned-active-sidecar',
          status: 'running',
          phase: 'running',
          workspaceRoot: cwd,
          sessionId: 'session-save-state-tombstoned-active',
          request: { secret: 'tombstoned active secret' },
          logFile: resolveJobLogFile(cwd, 'save-state-tombstoned-active-sidecar'),
          updatedAt: new Date().toISOString()
        };
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, 'TOMBSTONED_ACTIVE_LOG_SECRET\\n', 'utf8');
        updateState(cwd, (state) => {
          markSessionEnded(state, 'session-save-state-tombstoned-active');
        });
        saveState(cwd, { jobs: [] });
        const jobFile = resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          jobFileExists: fs.existsSync(jobFile),
          jobFileText: fs.existsSync(jobFile) ? fs.readFileSync(jobFile, 'utf8') : '',
          logFileExists: fs.existsSync(job.logFile),
          logFileText: fs.existsSync(job.logFile) ? fs.readFileSync(job.logFile, 'utf8') : ''
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["jobFileExists"] is False
    assert "tombstoned active secret" not in payload["jobFileText"]
    assert payload["logFileExists"] is False
    assert "TOMBSTONED_ACTIVE_LOG_SECRET" not in payload["logFileText"]


def test_codex_save_state_replacement_removes_sidecar_only_log_path(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          resolveJobFile,
          resolveJobLogFile,
          saveState,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const shared = {
          id: 'save-state-sidecar-log-only',
          status: 'completed',
          workspaceRoot: cwd,
          updatedAt: new Date().toISOString()
        };
        const sidecar = {
          ...shared,
          logFile: resolveJobLogFile(cwd, shared.id)
        };
        saveState(cwd, { jobs: [shared] });
        writeJobFile(cwd, shared.id, sidecar);
        fs.writeFileSync(sidecar.logFile, 'terminal secret log\\n', 'utf8');
        saveState(cwd, { jobs: [] });
        const jobFile = resolveJobFile(cwd, shared.id);

        console.log(JSON.stringify({
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(sidecar.logFile),
          logFileText: fs.existsSync(sidecar.logFile) ? fs.readFileSync(sidecar.logFile, 'utf8') : ''
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["jobFileExists"] is False
    assert payload["logFileExists"] is False
    assert "terminal secret log" not in payload["logFileText"]


def test_codex_save_state_replacement_removes_orphan_terminal_sidecars(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          resolveJobFile,
          resolveJobLogFile,
          saveState,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'save-state-orphan-terminal',
          status: 'completed',
          workspaceRoot: cwd,
          logFile: resolveJobLogFile(cwd, 'save-state-orphan-terminal'),
          updatedAt: new Date().toISOString()
        };
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, 'secret terminal log\\n', 'utf8');
        saveState(cwd, { jobs: [] });
        const jobFile = resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(job.logFile),
          logFileText: fs.existsSync(job.logFile) ? fs.readFileSync(job.logFile, 'utf8') : ''
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["jobFileExists"] is False
    assert payload["logFileExists"] is False
    assert "secret terminal log" not in payload["logFileText"]


def test_codex_state_skips_pruned_file_delete_when_job_reappears(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          listJobs,
          removePrunedJobFiles,
          resolveJobFile,
          resolveJobLogFile,
          saveState,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'reappeared-job',
          status: 'running',
          workspaceRoot: cwd,
          updatedAt: new Date().toISOString()
        };
        const logFile = resolveJobLogFile(cwd, job.id);
        saveState(cwd, { jobs: [job] });
        writeJobFile(cwd, job.id, { ...job, progress: 'new job file' });
        fs.writeFileSync(logFile, 'new log\\n', 'utf8');

        removePrunedJobFiles(cwd, [{ ...job, logFile }], []);

        console.log(JSON.stringify({
          stateHasJob: listJobs(cwd).some((item) => item.id === job.id),
          jobFileExists: fs.existsSync(resolveJobFile(cwd, job.id)),
          logFileExists: fs.existsSync(logFile)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload == {
        "stateHasJob": True,
        "jobFileExists": True,
        "logFileExists": True,
    }


def test_codex_state_skips_pruned_active_job_file(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          removePrunedJobFiles,
          resolveJobFile,
          resolveJobLogFile,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'active-pruned-job',
          status: 'running',
          workspaceRoot: cwd,
          updatedAt: new Date().toISOString()
        };
        const logFile = resolveJobLogFile(cwd, job.id);
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(logFile, 'active log\\n', 'utf8');

        removePrunedJobFiles(cwd, [{ ...job, logFile }], []);

        console.log(JSON.stringify({
          jobFileExists: fs.existsSync(resolveJobFile(cwd, job.id)),
          logFileExists: fs.existsSync(logFile)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload == {
        "jobFileExists": True,
        "logFileExists": True,
    }


def test_codex_state_prune_delete_does_not_race_child_upsert(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import { spawn } from 'node:child_process';
        import {
          listJobs,
          removePrunedJobFiles,
          resolveJobFile,
          resolveJobLogFile,
          saveState,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'child-reappeared-job',
          status: 'completed',
          workspaceRoot: cwd,
          updatedAt: new Date().toISOString()
        };
        const jobFile = resolveJobFile(cwd, job.id);
        const logFile = resolveJobLogFile(cwd, job.id);
        const publishedSignal = `${jobFile}.published`;
        writeJobFile(cwd, job.id, { ...job, progress: 'old job file' });
        fs.writeFileSync(logFile, 'old log\\n', 'utf8');

        let injected = false;
        let childStatus = null;
        let childStderr = '';
        let childDone = Promise.resolve();
        const originalUnlinkSync = fs.unlinkSync;
        fs.unlinkSync = function patchedUnlinkSync(filePath) {
          if (!injected && String(filePath) === jobFile) {
            injected = true;
            const child = spawn(
              process.execPath,
              [
                '--input-type=module',
                '-e',
                `
                  import fs from 'node:fs';
                  import {
                    resolveJobLogFile,
                    upsertJob,
                    writeJobFile
                  } from './plugins/codex/scripts/lib/state.mjs';
                  const cwd = process.argv[1];
                  const job = ${JSON.stringify(job)};
                  const logFile = resolveJobLogFile(cwd, job.id);
                  upsertJob(cwd, { ...job, childPublished: true, logFile });
                  fs.writeFileSync(process.argv[2], 'published', 'utf8');
                  writeJobFile(cwd, job.id, { ...job, childPublished: true, logFile });
                  fs.writeFileSync(logFile, 'new log\\\\n', 'utf8');
                `,
                cwd,
                publishedSignal
              ],
              {
                cwd: process.cwd(),
                env: {
                  ...process.env,
                  CODEX_FOR_CLAUDE_FILE_LOCK_WAIT_MS: '5000'
                },
              }
            );
            child.stderr.setEncoding('utf8');
            child.stderr.on('data', (chunk) => {
              childStderr += chunk;
            });
            childDone = new Promise((resolve) => {
              child.on('close', (status) => {
                childStatus = status;
                resolve();
              });
            });
            const startedAt = Date.now();
            while (!fs.existsSync(publishedSignal) && Date.now() - startedAt < 1000) {
              Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 20);
            }
          }
          return originalUnlinkSync.call(fs, filePath);
        };

        try {
          removePrunedJobFiles(cwd, [{ ...job, logFile }], []);
        } finally {
          fs.unlinkSync = originalUnlinkSync;
        }
        await childDone;

        const stateHasJob = listJobs(cwd).some((item) => item.id === job.id);
        console.log(JSON.stringify({
          injected,
          childStatus,
          childStderr,
          stateHasJob,
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(logFile),
          publishedSignalExists: fs.existsSync(publishedSignal)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["injected"] is True
    assert payload["publishedSignalExists"] is True
    assert payload["childStatus"] == 0, payload["childStderr"]
    assert payload["stateHasJob"] is True
    assert payload["jobFileExists"] is True
    assert payload["logFileExists"] is True


def test_codex_state_file_lock_wait_env_controls_timeout(tmp_path):
    state_source = read_text(PLUGIN / "scripts" / "lib" / "state.mjs")
    assert "CODEX_FOR_CLAUDE_FILE_LOCK_WAIT_MS" in state_source
    assert "LOCK_STALE_AFTER_MS + 5000" in state_source
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import path from 'node:path';
        import { resolveJobsDir, withJobFileLock } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        process.env.CODEX_FOR_CLAUDE_FILE_LOCK_WAIT_MS = '1';
        fs.mkdirSync(path.join(resolveJobsDir(cwd), '.wait-env.lock'), { recursive: true });
        const started = Date.now();
        let message = null;
        try {
          withJobFileLock(cwd, 'wait-env', () => {});
        } catch (error) {
          message = error.message;
        }
        console.log(JSON.stringify({ message, elapsedMs: Date.now() - started }));
        """,
        args=[str(tmp_path)],
    )
    assert "Timed out acquiring lock" in payload["message"]
    assert payload["elapsedMs"] < 1000


def test_codex_session_lifecycle_cleanup_uses_locked_update_state():
    source = read_text(PLUGIN / "scripts" / "session-lifecycle-hook.mjs")
    assert "saveState" not in source
    assert "updateState" in source
    assert "removeJobSidecar" in source
    assert "listJobSidecars" in source
    cleanup = js_function_body(source, "cleanupSessionJobs")
    assert "updateState(workspaceRoot" in cleanup
    assert "markSessionEnded(state, sessionId)" in cleanup
    assert "let removedJobs = []" in cleanup
    assert "removedJobs = state.jobs.filter((job) => job.sessionId === sessionId)" in cleanup
    assert "state.jobs = state.jobs.filter((job) => job.sessionId !== sessionId)" in cleanup
    assert "for (const job of listJobSidecars(workspaceRoot))" in cleanup
    assert cleanup.index("removedJobs = state.jobs.filter((job) => job.sessionId === sessionId)") < cleanup.index("state.jobs = state.jobs.filter((job) => job.sessionId !== sessionId)")
    assert cleanup.index("updateState(workspaceRoot") < cleanup.index("removeJobSidecar(workspaceRoot, job)")


def test_codex_session_lifecycle_cleanup_removes_active_sidecars(tmp_path):
    payload = run_node_script(
        f"""
        import fs from 'node:fs';
        import {{ spawnSync }} from 'node:child_process';
        import {{
          listJobs,
          resolveJobFile,
          resolveJobLogFile,
          upsertJob,
          writeJobFile
        }} from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const hook = {json.dumps(str(PLUGIN / "scripts" / "session-lifecycle-hook.mjs"))};
        const job = {{
          id: 'session-active-cleanup',
          status: 'running',
          workspaceRoot: cwd,
          sessionId: 'session-cleanup',
          pid: 99999999,
          request: {{ secret: true }},
          logFile: resolveJobLogFile(cwd, 'session-active-cleanup'),
          updatedAt: new Date().toISOString()
        }};
        upsertJob(cwd, job);
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, 'active log\\\\n', 'utf8');

        const result = spawnSync(
          process.execPath,
          [hook, 'SessionEnd'],
          {{
            cwd,
            input: JSON.stringify({{ cwd, session_id: 'session-cleanup' }}),
            encoding: 'utf8'
          }}
        );

        console.log(JSON.stringify({{
          status: result.status,
          stderr: result.stderr,
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(resolveJobFile(cwd, job.id)),
          logFileExists: fs.existsSync(job.logFile)
        }}));
        """,
        args=[str(tmp_path)],
    )

    assert payload["status"] == 0, payload["stderr"]
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert payload["logFileExists"] is False


def test_codex_session_lifecycle_cleanup_removes_state_and_sidecar_log_paths(tmp_path):
    payload = run_node_script(
        f"""
        import fs from 'node:fs';
        import {{ spawnSync }} from 'node:child_process';
        import {{
          listJobs,
          resolveJobFile,
          resolveJobLogFile,
          upsertJob,
          writeJobFile
        }} from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const hook = {json.dumps(str(PLUGIN / "scripts" / "session-lifecycle-hook.mjs"))};
        const oldLog = resolveJobLogFile(cwd, 'session-mismatch-old');
        const actualLog = resolveJobLogFile(cwd, 'session-mismatch-actual');
        const sharedJob = {{
          id: 'session-mismatched-log-cleanup',
          status: 'running',
          workspaceRoot: cwd,
          sessionId: 'session-mismatched-log',
          pid: 99999999,
          request: {{ secret: 'state secret' }},
          logFile: oldLog,
          updatedAt: new Date().toISOString()
        }};
        const sidecarJob = {{
          ...sharedJob,
          request: {{ secret: 'sidecar secret' }},
          logFile: actualLog
        }};
        upsertJob(cwd, sharedJob);
        writeJobFile(cwd, sharedJob.id, sidecarJob);
        fs.writeFileSync(oldLog, 'OLD_SECRET_LOG\\\\n', 'utf8');
        fs.writeFileSync(actualLog, 'SIDE_SECRET_LOG\\\\n', 'utf8');

        const result = spawnSync(
          process.execPath,
          [hook, 'SessionEnd'],
          {{
            cwd,
            input: JSON.stringify({{ cwd, session_id: 'session-mismatched-log' }}),
            encoding: 'utf8'
          }}
        );

        console.log(JSON.stringify({{
          status: result.status,
          stderr: result.stderr,
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(resolveJobFile(cwd, sharedJob.id)),
          oldLogExists: fs.existsSync(oldLog),
          sidecarLogExists: fs.existsSync(actualLog),
          sidecarLogText: fs.existsSync(actualLog) ? fs.readFileSync(actualLog, 'utf8') : ''
        }}));
        """,
        args=[str(tmp_path)],
    )

    assert payload["status"] == 0, payload["stderr"]
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert payload["oldLogExists"] is False
    assert payload["sidecarLogExists"] is False
    assert "SIDE_SECRET_LOG" not in payload["sidecarLogText"]


def test_codex_session_lifecycle_cleanup_removes_jobs_added_after_snapshot(tmp_path):
    payload = run_node_script(
        f"""
        import fs from 'node:fs';
        import path from 'node:path';
        import {{ spawnSync }} from 'node:child_process';
        import {{
          listJobs,
          resolveJobFile,
          resolveJobLogFile,
          resolveStateFile,
          upsertJob,
          writeJobFile
        }} from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const hook = {json.dumps(str(PLUGIN / "scripts" / "session-lifecycle-hook.mjs"))};
        const initialJob = {{
          id: 'session-snapshot-cleanup',
          status: 'running',
          workspaceRoot: cwd,
          sessionId: 'session-cleanup-race',
          pid: 99999999,
          request: {{ secret: 'initial' }},
          logFile: resolveJobLogFile(cwd, 'session-snapshot-cleanup'),
          updatedAt: new Date().toISOString()
        }};
        const injectedJob = {{
          id: 'session-injected-cleanup',
          status: 'running',
          workspaceRoot: cwd,
          sessionId: 'session-cleanup-race',
          pid: 99999999,
          request: {{ secret: 'injected' }},
          logFile: resolveJobLogFile(cwd, 'session-injected-cleanup'),
          updatedAt: new Date().toISOString()
        }};
        upsertJob(cwd, initialJob);
        writeJobFile(cwd, initialJob.id, initialJob);
        fs.writeFileSync(initialJob.logFile, 'initial log\\\\n', 'utf8');

        const preload = path.join(cwd, 'inject-after-first-state-read.cjs');
        fs.writeFileSync(preload, `
          const fs = require('node:fs');
          const path = require('node:path');
          const originalReadFileSync = fs.readFileSync;
          let injected = false;
          fs.readFileSync = function patchedReadFileSync(file, ...args) {{
            const result = originalReadFileSync.call(this, file, ...args);
            if (!injected && String(file) === process.env.CODEX_TEST_STATE_FILE) {{
              injected = true;
              const job = JSON.parse(process.env.CODEX_TEST_INJECT_JOB);
              const state = JSON.parse(String(result));
              state.jobs = [...(state.jobs || []), job];
              fs.writeFileSync(process.env.CODEX_TEST_STATE_FILE, JSON.stringify(state, null, 2) + "\\\\n", 'utf8');
              fs.mkdirSync(path.dirname(process.env.CODEX_TEST_INJECT_JOB_FILE), {{ recursive: true }});
              fs.writeFileSync(process.env.CODEX_TEST_INJECT_JOB_FILE, JSON.stringify(job, null, 2) + "\\\\n", 'utf8');
              fs.writeFileSync(job.logFile, 'injected log\\\\n', 'utf8');
            }}
            return result;
          }};
        `, 'utf8');

        const result = spawnSync(
          process.execPath,
          [hook, 'SessionEnd'],
          {{
            cwd,
            input: JSON.stringify({{ cwd, session_id: 'session-cleanup-race' }}),
            encoding: 'utf8',
            env: {{
              ...process.env,
              NODE_OPTIONS: `--require ${{preload}}`,
              CODEX_TEST_STATE_FILE: resolveStateFile(cwd),
              CODEX_TEST_INJECT_JOB: JSON.stringify(injectedJob),
              CODEX_TEST_INJECT_JOB_FILE: resolveJobFile(cwd, injectedJob.id)
            }}
          }}
        );

        console.log(JSON.stringify({{
          status: result.status,
          stderr: result.stderr,
          jobs: listJobs(cwd),
          initialJobFileExists: fs.existsSync(resolveJobFile(cwd, initialJob.id)),
          initialLogFileExists: fs.existsSync(initialJob.logFile),
          injectedJobFileExists: fs.existsSync(resolveJobFile(cwd, injectedJob.id)),
          injectedLogFileExists: fs.existsSync(injectedJob.logFile)
        }}));
        """,
        args=[str(tmp_path)],
    )

    assert payload["status"] == 0, payload["stderr"]
    assert payload["jobs"] == []
    assert payload["initialJobFileExists"] is False
    assert payload["initialLogFileExists"] is False
    assert payload["injectedJobFileExists"] is False
    assert payload["injectedLogFileExists"] is False


def test_codex_session_lifecycle_records_ended_session_without_jobs(tmp_path):
    payload = run_node_script(
        f"""
        import {{ spawnSync }} from 'node:child_process';
        import {{
          hasEndedSession,
          listJobs
        }} from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const hook = {json.dumps(str(PLUGIN / "scripts" / "session-lifecycle-hook.mjs"))};
        const result = spawnSync(
          process.execPath,
          [hook, 'SessionEnd'],
          {{
            cwd,
            input: JSON.stringify({{ cwd, session_id: 'session-empty-cleanup' }}),
            encoding: 'utf8'
          }}
        );

        console.log(JSON.stringify({{
          status: result.status,
          stderr: result.stderr,
          ended: hasEndedSession(cwd, 'session-empty-cleanup'),
          jobs: listJobs(cwd)
        }}));
        """,
        args=[str(tmp_path)],
    )

    assert payload["status"] == 0, payload["stderr"]
    assert payload["ended"] is True
    assert payload["jobs"] == []


def test_codex_session_lifecycle_removes_pruned_active_sidecars(tmp_path):
    payload = run_node_script(
        f"""
        import fs from 'node:fs';
        import {{ spawnSync }} from 'node:child_process';
        import {{
          listJobs,
          resolveJobFile,
          resolveJobLogFile,
          saveState,
          writeJobFile
        }} from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const hook = {json.dumps(str(PLUGIN / "scripts" / "session-lifecycle-hook.mjs"))};
        const active = {{
          id: 'session-pruned-active-cleanup',
          status: 'running',
          workspaceRoot: cwd,
          sessionId: 'session-pruned-cleanup',
          pid: 99999999,
          request: {{ secret: 'pruned active secret' }},
          logFile: resolveJobLogFile(cwd, 'session-pruned-active-cleanup'),
          updatedAt: '2000-01-01T00:00:00.000Z'
        }};
        writeJobFile(cwd, active.id, active);
        fs.writeFileSync(active.logFile, 'pruned active log\\\\n', 'utf8');
        const newerJobs = Array.from({{ length: 51 }}, (_, index) => ({{
          id: `newer-job-${{index}}`,
          status: 'completed',
          workspaceRoot: cwd,
          sessionId: `other-session-${{index}}`,
          updatedAt: new Date(Date.now() + index).toISOString()
        }}));
        saveState(cwd, {{ jobs: [active, ...newerJobs] }});

        const result = spawnSync(
          process.execPath,
          [hook, 'SessionEnd'],
          {{
            cwd,
            input: JSON.stringify({{ cwd, session_id: 'session-pruned-cleanup' }}),
            encoding: 'utf8'
          }}
        );
        const jobFile = resolveJobFile(cwd, active.id);

        console.log(JSON.stringify({{
          status: result.status,
          stderr: result.stderr,
          sharedHasActive: listJobs(cwd).some((job) => job.id === active.id),
          jobFileExists: fs.existsSync(jobFile),
          jobFileText: fs.existsSync(jobFile) ? fs.readFileSync(jobFile, 'utf8') : '',
          logFileExists: fs.existsSync(active.logFile)
        }}));
        """,
        args=[str(tmp_path)],
    )

    assert payload["status"] == 0, payload["stderr"]
    assert payload["sharedHasActive"] is False
    assert payload["jobFileExists"] is False
    assert "pruned active secret" not in payload["jobFileText"]
    assert payload["logFileExists"] is False


def test_codex_state_lock_order_is_one_way():
    source = read_text(PLUGIN / "scripts" / "lib" / "state.mjs")
    assert "const LOCK_CONTEXT" in source
    assert "LOCK_CONTEXT.stateDepth" in source
    assert "LOCK_CONTEXT.jobDepth" in source
    with_state = js_function_body(source, "withStateLock")
    with_job = js_function_body(source, "withJobFileLock")
    assert "LOCK_CONTEXT.jobDepth" in with_state
    assert "state lock cannot be acquired while holding a job-file lock" in with_state
    assert "LOCK_CONTEXT.stateDepth" in with_job
    assert "job-file lock cannot be acquired while holding a state lock" in with_job
    assert "LOCK_CONTEXT.jobDepth" in with_job
    assert "job-file lock cannot be nested" in with_job


def test_codex_job_file_lock_enforces_runtime_order(tmp_path):
    payload = run_node_script(
        """
        import { mutateJobFile, updateState, withJobFileLock, withStateLock } from './plugins/codex/scripts/lib/state.mjs';
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
        const jobInsideState = (() => {
          try {
            withStateLock(cwd, () => withJobFileLock(cwd, 'job-lock-order', () => {}));
            return null;
          } catch (error) {
            return error.message;
          }
        })();
        console.log(JSON.stringify({ nestedJob, stateInsideJob, jobInsideState }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["nestedJob"] == "job-file lock cannot be nested"
    assert payload["stateInsideJob"] == "state lock cannot be acquired while holding a job-file lock"
    assert payload["jobInsideState"] == "job-file lock cannot be acquired while holding a state lock"


def test_codex_progress_upsert_prune_completes_before_job_file_mutation():
    source = read_text(PLUGIN / "scripts" / "lib" / "tracked-jobs.mjs")
    body = js_function_body(source, "createJobProgressUpdater")
    assert "function sharedProgressJobPatch(job)" in source
    assert "pruneJobFiles: false" in js_function_body(source, "removeOrphanProgressPatch")
    assert "sharedProgressJobPatch(restoreJob)" in js_function_body(source, "removeOrphanProgressPatch")
    assert "fallbackTerminalJob" in js_function_body(source, "removeOrphanProgressPatch")
    assert "request," in js_function_body(source, "sharedProgressJobPatch")
    assert "result," in js_function_body(source, "sharedProgressJobPatch")
    assert body.index("upsertJob(workspaceRoot, patch)") < body.index("mutateJobFile(workspaceRoot, jobId")
    assert body.index("mutateJobFile(workspaceRoot, jobId") < body.index("upsertJob(workspaceRoot, sharedProgressJobPatch(updated))")
    assert "removeOrphanProgressPatch(workspaceRoot, jobId, terminalJob, originalSharedJob)" in body
    assert "if (!updated)" in body


def test_codex_progress_update_does_not_publish_orphan_shared_job(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          createJobProgressUpdater
        } from './plugins/codex/scripts/lib/tracked-jobs.mjs';
        import {
          listJobs,
          resolveJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const update = createJobProgressUpdater(cwd, 'missing-progress-job');
        update({ phase: 'running', threadId: 'thread-1' });

        console.log(JSON.stringify({
          sharedJob: listJobs(cwd).find((job) => job.id === 'missing-progress-job') ?? null,
          jobFileExists: fs.existsSync(resolveJobFile(cwd, 'missing-progress-job'))
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload == {
        "sharedJob": None,
        "jobFileExists": False,
    }


def test_codex_progress_update_restores_complete_active_shared_job(tmp_path):
    payload = run_node_script(
        """
        import {
          createJobProgressUpdater
        } from './plugins/codex/scripts/lib/tracked-jobs.mjs';
        import {
          listJobs,
          removePrunedJobFiles,
          resolveJobLogFile,
          saveState,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'active-pruned-restore',
          status: 'running',
          kind: 'task',
          title: 'Active restore',
          workspaceRoot: cwd,
          phase: 'starting',
          pid: process.pid,
          sessionId: 'session-1',
          request: { secret: true },
          result: { heavy: true },
          rendered: 'large output',
          backgroundLeaseId: 'lease-1',
          logFile: resolveJobLogFile(cwd, 'active-pruned-restore'),
          updatedAt: new Date().toISOString()
        };
        saveState(cwd, { jobs: [] });
        writeJobFile(cwd, job.id, job);
        removePrunedJobFiles(cwd, [job], []);

        const update = createJobProgressUpdater(cwd, job.id);
        update({ phase: 'running', threadId: 'thread-1' });
        const sharedJob = listJobs(cwd).find((item) => item.id === job.id) ?? null;

        console.log(JSON.stringify({ sharedJob }));
        """,
        args=[str(tmp_path)],
    )

    shared = payload["sharedJob"]
    assert shared["id"] == "active-pruned-restore"
    assert shared["status"] == "running"
    assert shared["workspaceRoot"] == str(tmp_path)
    assert shared["kind"] == "task"
    assert shared["title"] == "Active restore"
    assert shared["phase"] == "running"
    assert shared["threadId"] == "thread-1"
    assert shared["logFile"]
    assert "request" not in shared
    assert "result" not in shared
    assert "rendered" not in shared
    assert "backgroundLeaseId" not in shared


def test_codex_progress_update_after_session_end_removes_sidecar_without_republish(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          createJobProgressUpdater
        } from './plugins/codex/scripts/lib/tracked-jobs.mjs';
        import {
          listJobs,
          markSessionEnded,
          resolveJobFile,
          resolveJobLogFile,
          updateState,
          upsertJob,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'progress-ended-session',
          status: 'running',
          kind: 'task',
          title: 'Progress ended session',
          workspaceRoot: cwd,
          sessionId: 'session-progress-ended',
          phase: 'starting',
          pid: process.pid,
          request: { secret: 'progress secret' },
          logFile: resolveJobLogFile(cwd, 'progress-ended-session'),
          updatedAt: new Date().toISOString()
        };
        upsertJob(cwd, job);
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, 'progress log\\n', 'utf8');
        updateState(cwd, (state) => {
          markSessionEnded(state, 'session-progress-ended');
          state.jobs = state.jobs.filter((item) => item.sessionId !== 'session-progress-ended');
        });

        const update = createJobProgressUpdater(cwd, job.id);
        update({ phase: 'running', threadId: 'thread-ended' });
        const jobFile = resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          jobFileText: fs.existsSync(jobFile) ? fs.readFileSync(jobFile, 'utf8') : '',
          logFileExists: fs.existsSync(job.logFile)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert "progress secret" not in payload["jobFileText"]
    assert payload["logFileExists"] is False


def test_codex_progress_update_ignores_terminal_sidecar_without_republish(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          createJobProgressUpdater
        } from './plugins/codex/scripts/lib/tracked-jobs.mjs';
        import {
          listJobs,
          readJobFile,
          resolveJobFile,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'progress-terminal-sidecar',
          status: 'completed',
          phase: 'done',
          workspaceRoot: cwd,
          completedAt: new Date().toISOString()
        };
        writeJobFile(cwd, job.id, job);
        const update = createJobProgressUpdater(cwd, job.id);
        update({ phase: 'running', threadId: 'thread-late-progress' });
        const jobFile = resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          jobs: listJobs(cwd),
          stored: readJobFile(jobFile)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["jobs"] == []
    assert payload["stored"]["status"] == "completed"
    assert payload["stored"]["phase"] == "done"
    assert "threadId" not in payload["stored"]


def test_codex_progress_update_preserves_shared_terminal_job(tmp_path):
    payload = run_node_script(
        """
        import {
          createJobProgressUpdater
        } from './plugins/codex/scripts/lib/tracked-jobs.mjs';
        import {
          listJobs,
          upsertJob,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'progress-shared-terminal',
          status: 'completed',
          phase: 'done',
          workspaceRoot: cwd,
          threadId: 'thread-final',
          turnId: 'turn-final',
          completedAt: new Date().toISOString(),
          updatedAt: '2026-01-01T00:00:00.000Z'
        };
        upsertJob(cwd, job);
        writeJobFile(cwd, job.id, job);
        const update = createJobProgressUpdater(cwd, job.id);
        update({ phase: 'running', threadId: 'thread-late-progress' });

        console.log(JSON.stringify({
          jobs: listJobs(cwd)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert len(payload["jobs"]) == 1
    job = payload["jobs"][0]
    assert job["status"] == "completed"
    assert job["phase"] == "done"
    assert job["threadId"] == "thread-final"
    assert job["turnId"] == "turn-final"


def test_codex_progress_update_preserves_shared_terminal_job_without_sidecar(tmp_path):
    payload = run_node_script(
        """
        import {
          createJobProgressUpdater
        } from './plugins/codex/scripts/lib/tracked-jobs.mjs';
        import {
          listJobs,
          upsertJob
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'progress-shared-terminal-no-sidecar',
          status: 'completed',
          phase: 'done',
          workspaceRoot: cwd,
          threadId: 'thread-final',
          turnId: 'turn-final',
          completedAt: new Date().toISOString(),
          updatedAt: '2026-01-01T00:00:00.000Z'
        };
        upsertJob(cwd, job);
        const update = createJobProgressUpdater(cwd, job.id);
        update({ phase: 'running', threadId: 'thread-late-progress' });

        console.log(JSON.stringify({
          jobs: listJobs(cwd)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert len(payload["jobs"]) == 1
    job = payload["jobs"][0]
    assert job["status"] == "completed"
    assert job["phase"] == "done"
    assert job["threadId"] == "thread-final"
    assert job["turnId"] == "turn-final"


def test_codex_progress_log_only_after_session_end_does_not_recreate_log(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          createJobProgressUpdater,
          createProgressReporter
        } from './plugins/codex/scripts/lib/tracked-jobs.mjs';
        import {
          listJobs,
          markSessionEnded,
          removeJobSidecar,
          resolveJobFile,
          resolveJobLogFile,
          updateState,
          upsertJob,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'progress-log-ended-session',
          status: 'running',
          kind: 'task',
          title: 'Progress log ended session',
          workspaceRoot: cwd,
          sessionId: 'session-progress-log-ended',
          phase: 'starting',
          pid: process.pid,
          request: { secret: 'progress log secret' },
          logFile: resolveJobLogFile(cwd, 'progress-log-ended-session'),
          updatedAt: new Date().toISOString()
        };
        upsertJob(cwd, job);
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, 'progress log\\n', 'utf8');
        const update = createJobProgressUpdater(cwd, job.id);
        update({ phase: 'investigating' });
        updateState(cwd, (state) => {
          markSessionEnded(state, 'session-progress-log-ended');
          state.jobs = state.jobs.filter((item) => item.sessionId !== 'session-progress-log-ended');
        });
        removeJobSidecar(cwd, job);

        const reporter = createProgressReporter({
          logFile: job.logFile,
          job,
          onEvent: update
        });
        reporter({
          phase: 'investigating',
          message: 'late same phase',
          logTitle: 'Late progress',
          logBody: 'SECRET_AFTER_SESSION_END'
        });
        const jobFile = resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(job.logFile),
          logFileText: fs.existsSync(job.logFile) ? fs.readFileSync(job.logFile, 'utf8') : ''
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert payload["logFileExists"] is False
    assert "SECRET_AFTER_SESSION_END" not in payload["logFileText"]


def test_codex_progress_reporter_does_not_log_after_session_end_between_gate_and_append(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          createJobProgressUpdater,
          createProgressReporter
        } from './plugins/codex/scripts/lib/tracked-jobs.mjs';
        import {
          listJobs,
          markSessionEnded,
          removeJobSidecar,
          resolveJobFile,
          resolveJobLogFile,
          updateState,
          upsertJob,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'progress-gate-append-race',
          status: 'running',
          kind: 'task',
          title: 'Progress gate append race',
          workspaceRoot: cwd,
          sessionId: 'session-progress-gate-append',
          phase: 'starting',
          pid: process.pid,
          logFile: resolveJobLogFile(cwd, 'progress-gate-append-race'),
          updatedAt: new Date().toISOString()
        };
        upsertJob(cwd, job);
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, 'progress log\\n', 'utf8');
        const update = createJobProgressUpdater(cwd, job.id);
        update({ phase: 'investigating' });
        const reporter = createProgressReporter({
          logFile: job.logFile,
          job,
          onEvent: (event) => {
            const accepted = update(event);
            if (accepted !== false) {
              updateState(cwd, (state) => {
                markSessionEnded(state, 'session-progress-gate-append');
                state.jobs = state.jobs.filter((item) => item.sessionId !== 'session-progress-gate-append');
              });
              removeJobSidecar(cwd, job);
            }
            return accepted;
          }
        });
        reporter({
          phase: 'investigating',
          message: 'late same phase',
          logTitle: 'Late progress',
          logBody: 'SECRET_AFTER_SESSION_END'
        });
        const jobFile = resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(job.logFile),
          logFileText: fs.existsSync(job.logFile) ? fs.readFileSync(job.logFile, 'utf8') : ''
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert payload["logFileExists"] is False
    assert "SECRET_AFTER_SESSION_END" not in payload["logFileText"]


def test_codex_generic_progress_reporter_ignores_on_event_return_value(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          createProgressReporter
        } from './plugins/codex/scripts/lib/tracked-jobs.mjs';

        const logFile = process.argv[1];
        const reporter = createProgressReporter({
          logFile,
          onEvent() {
            return false;
          }
        });
        reporter({
          message: 'generic progress line',
          logTitle: 'Generic block',
          logBody: 'generic progress body'
        });
        console.log(JSON.stringify({
          logFileExists: fs.existsSync(logFile),
          logFileText: fs.existsSync(logFile) ? fs.readFileSync(logFile, 'utf8') : ''
        }));
        """,
        args=[str(tmp_path / "generic-progress.log")],
    )

    assert payload["logFileExists"] is True
    assert "generic progress line" in payload["logFileText"]
    assert "generic progress body" in payload["logFileText"]


def test_codex_run_tracked_job_completion_after_session_end_does_not_republish_result(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          runTrackedJob
        } from './plugins/codex/scripts/lib/tracked-jobs.mjs';
        import {
          listJobs,
          markSessionEnded,
          resolveJobFile,
          resolveJobLogFile,
          updateState
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'terminal-ended-session',
          status: 'queued',
          kind: 'task',
          title: 'Terminal ended session',
          workspaceRoot: cwd,
          sessionId: 'session-terminal-ended',
          phase: 'queued',
          pid: null,
          logFile: resolveJobLogFile(cwd, 'terminal-ended-session')
        };
        const execution = await runTrackedJob(
          job,
          async () => {
            updateState(cwd, (state) => {
              markSessionEnded(state, 'session-terminal-ended');
              state.jobs = state.jobs.filter((item) => item.sessionId !== 'session-terminal-ended');
            });
            return {
              exitStatus: 0,
              threadId: 'thread-terminal',
              turnId: 'turn-terminal',
              summary: 'terminal summary',
              payload: { secret: 'terminal secret' },
              rendered: 'terminal rendered secret'
            };
          },
          { logFile: job.logFile }
        );
        const jobFile = resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          executionStatus: execution.exitStatus,
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          jobFileText: fs.existsSync(jobFile) ? fs.readFileSync(jobFile, 'utf8') : '',
          logFileExists: fs.existsSync(job.logFile)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["executionStatus"] == 0
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert "terminal secret" not in payload["jobFileText"]
    assert payload["logFileExists"] is False


def test_codex_run_tracked_job_does_not_recreate_log_when_terminal_write_rejected(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';

        const cwd = process.argv[1];
        const originalRenameSync = fs.renameSync;
        let injected = false;
        fs.renameSync = function patchedRenameSync(from, to) {
          originalRenameSync.call(this, from, to);
          if (injected || !String(to).endsWith('/state.json')) {
            return;
          }
          try {
            const state = JSON.parse(fs.readFileSync(to, 'utf8'));
            const hasCompleted = state.jobs?.some((job) => job.id === 'terminal-log-race' && job.status === 'completed');
            if (!hasCompleted) {
              return;
            }
            injected = true;
            state.endedSessions = [...(state.endedSessions || []), 'session-terminal-log-race'];
            state.jobs = state.jobs.filter((job) => job.id !== 'terminal-log-race');
            fs.writeFileSync(to, `${JSON.stringify(state, null, 2)}\\n`, 'utf8');
          } catch {
            // Non-state files or transient partial reads are irrelevant for this test.
          }
        };

        const tracked = await import('./plugins/codex/scripts/lib/tracked-jobs.mjs');
        const state = await import('./plugins/codex/scripts/lib/state.mjs');
        const job = {
          id: 'terminal-log-race',
          status: 'queued',
          kind: 'task',
          title: 'Terminal log race',
          workspaceRoot: cwd,
          sessionId: 'session-terminal-log-race',
          phase: 'queued',
          pid: null,
          logFile: state.resolveJobLogFile(cwd, 'terminal-log-race')
        };
        const execution = await tracked.runTrackedJob(
          job,
          async () => ({
            exitStatus: 0,
            threadId: 'thread-log-race',
            turnId: 'turn-log-race',
            summary: 'terminal log summary',
            payload: { secret: 'terminal log secret' },
            rendered: 'terminal log rendered secret'
          }),
          { logFile: job.logFile }
        );
        const jobFile = state.resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          executionStatus: execution.exitStatus,
          jobs: state.listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(job.logFile),
          logFileText: fs.existsSync(job.logFile) ? fs.readFileSync(job.logFile, 'utf8') : ''
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["executionStatus"] == 0
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert payload["logFileExists"] is False
    assert "terminal log rendered secret" not in payload["logFileText"]


def test_codex_run_tracked_job_does_not_recreate_log_after_terminal_sidecar_cleanup(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import path from 'node:path';

        const cwd = process.argv[1];
        const originalRenameSync = fs.renameSync;
        let injected = false;
        fs.renameSync = function patchedRenameSync(from, to) {
          originalRenameSync.call(this, from, to);
          if (injected || !String(to).endsWith('/terminal-final-output-race.json')) {
            return;
          }
          try {
            const stored = JSON.parse(fs.readFileSync(to, 'utf8'));
            if (stored.status !== 'completed') {
              return;
            }
            injected = true;
            const jobsDir = path.dirname(to);
            const stateFile = path.join(path.dirname(jobsDir), 'state.json');
            const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
            state.endedSessions = [...(state.endedSessions || []), 'session-terminal-final-output-race'];
            state.jobs = state.jobs.filter((job) => job.id !== 'terminal-final-output-race');
            fs.writeFileSync(stateFile, `${JSON.stringify(state, null, 2)}\\n`, 'utf8');
            fs.rmSync(to, { force: true });
            fs.rmSync(path.join(jobsDir, 'terminal-final-output-race.log'), { force: true });
          } catch {
            // Non-target rename calls are irrelevant for this race injection.
          }
        };

        const tracked = await import('./plugins/codex/scripts/lib/tracked-jobs.mjs');
        const state = await import('./plugins/codex/scripts/lib/state.mjs');
        const job = {
          id: 'terminal-final-output-race',
          status: 'queued',
          kind: 'task',
          title: 'Terminal final output race',
          workspaceRoot: cwd,
          sessionId: 'session-terminal-final-output-race',
          phase: 'queued',
          pid: null,
          logFile: state.resolveJobLogFile(cwd, 'terminal-final-output-race')
        };
        fs.writeFileSync(job.logFile, 'running log\\n', 'utf8');
        const execution = await tracked.runTrackedJob(
          job,
          async () => ({
            exitStatus: 0,
            threadId: 'thread-final-output-race',
            turnId: 'turn-final-output-race',
            summary: 'terminal final output summary',
            payload: { secret: 'terminal final output secret' },
            rendered: 'FINAL_LOG_RENDERED_SECRET'
          }),
          { logFile: job.logFile }
        );
        const jobFile = state.resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          executionStatus: execution.exitStatus,
          injected,
          jobs: state.listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(job.logFile),
          logFileText: fs.existsSync(job.logFile) ? fs.readFileSync(job.logFile, 'utf8') : ''
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["executionStatus"] == 0
    assert payload["injected"] is True
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert payload["logFileExists"] is False
    assert "FINAL_LOG_RENDERED_SECRET" not in payload["logFileText"]


def test_codex_run_tracked_job_does_not_start_runner_when_running_write_rejected(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';

        const cwd = process.argv[1];
        const originalRenameSync = fs.renameSync;
        let injected = false;
        fs.renameSync = function patchedRenameSync(from, to) {
          originalRenameSync.call(this, from, to);
          if (injected || !String(to).endsWith('/state.json')) {
            return;
          }
          try {
            const state = JSON.parse(fs.readFileSync(to, 'utf8'));
            const hasRunning = state.jobs?.some((job) => job.id === 'running-write-race' && job.status === 'running');
            if (!hasRunning) {
              return;
            }
            injected = true;
            state.endedSessions = [...(state.endedSessions || []), 'session-running-write-race'];
            state.jobs = state.jobs.filter((job) => job.id !== 'running-write-race');
            fs.writeFileSync(to, `${JSON.stringify(state, null, 2)}\\n`, 'utf8');
          } catch {
            // Non-state files or transient partial reads are irrelevant for this test.
          }
        };

        const tracked = await import('./plugins/codex/scripts/lib/tracked-jobs.mjs');
        const state = await import('./plugins/codex/scripts/lib/state.mjs');
        let runnerStarted = false;
        let errorMessage = '';
        const job = {
          id: 'running-write-race',
          status: 'queued',
          kind: 'task',
          title: 'Running write race',
          workspaceRoot: cwd,
          sessionId: 'session-running-write-race',
          phase: 'queued',
          pid: null,
          logFile: state.resolveJobLogFile(cwd, 'running-write-race')
        };
        try {
          await tracked.runTrackedJob(
            job,
            async () => {
              runnerStarted = true;
              return {
                exitStatus: 0,
                threadId: 'thread-running-write-race',
                turnId: 'turn-running-write-race',
                summary: 'should not run',
                payload: {},
                rendered: 'should not render'
              };
            },
            { logFile: job.logFile }
          );
        } catch (error) {
          errorMessage = error instanceof Error ? error.message : String(error);
        }
        const jobFile = state.resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          runnerStarted,
          errorMessage,
          jobs: state.listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(job.logFile)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["runnerStarted"] is False
    assert "ended before job running-write-race could run" in payload["errorMessage"]
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert payload["logFileExists"] is False


def test_codex_run_tracked_job_does_not_start_runner_when_initial_heartbeat_rejected(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';

        const cwd = process.argv[1];
        const originalRenameSync = fs.renameSync;
        let injected = false;
        fs.renameSync = function patchedRenameSync(from, to) {
          originalRenameSync.call(this, from, to);
          if (injected || !String(to).endsWith('/heartbeat-start-race.json')) {
            return;
          }
          try {
            const stored = JSON.parse(fs.readFileSync(to, 'utf8'));
            if (stored.status !== 'running') {
              return;
            }
            injected = true;
            const stateFile = String(to).replace(/\\/jobs\\/heartbeat-start-race\\.json$/, '/state.json');
            const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
            state.endedSessions = [...(state.endedSessions || []), 'session-heartbeat-start-race'];
            state.jobs = state.jobs.filter((job) => job.id !== 'heartbeat-start-race');
            fs.writeFileSync(stateFile, `${JSON.stringify(state, null, 2)}\\n`, 'utf8');
          } catch {
            // Non-target rename calls are irrelevant for this race injection.
          }
        };

        const tracked = await import('./plugins/codex/scripts/lib/tracked-jobs.mjs');
        const state = await import('./plugins/codex/scripts/lib/state.mjs');
        let runnerStarted = false;
        let errorMessage = '';
        const job = {
          id: 'heartbeat-start-race',
          status: 'queued',
          kind: 'task',
          title: 'Heartbeat start race',
          workspaceRoot: cwd,
          sessionId: 'session-heartbeat-start-race',
          phase: 'queued',
          pid: null,
          logFile: state.resolveJobLogFile(cwd, 'heartbeat-start-race')
        };
        fs.writeFileSync(job.logFile, 'heartbeat start log\\n', 'utf8');
        try {
          await tracked.runTrackedJob(
            job,
            async () => {
              runnerStarted = true;
              return {
                exitStatus: 0,
                threadId: 'thread-heartbeat-start-race',
                turnId: 'turn-heartbeat-start-race',
                summary: 'should not run',
                payload: {},
                rendered: 'should not render'
              };
            },
            { logFile: job.logFile }
          );
        } catch (error) {
          errorMessage = error instanceof Error ? error.message : String(error);
        }
        const jobFile = state.resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          injected,
          runnerStarted,
          errorMessage,
          jobs: state.listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(job.logFile)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["injected"] is True
    assert payload["runnerStarted"] is False
    assert "ended before job heartbeat-start-race could run" in payload["errorMessage"]
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert payload["logFileExists"] is False


def test_codex_run_tracked_job_starts_when_heartbeat_disabled(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          runTrackedJob
        } from './plugins/codex/scripts/lib/tracked-jobs.mjs';
        import {
          listJobs,
          readJobFile,
          resolveJobFile,
          resolveJobLogFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        process.env.CODEX_FOR_CLAUDE_DISABLE_HEARTBEAT = '1';
        let runnerStarted = false;
        const job = {
          id: 'disable-heartbeat-run',
          status: 'queued',
          kind: 'task',
          title: 'Disable heartbeat run',
          workspaceRoot: cwd,
          sessionId: 'session-disable-heartbeat',
          phase: 'queued',
          pid: null,
          logFile: resolveJobLogFile(cwd, 'disable-heartbeat-run')
        };
        const execution = await runTrackedJob(
          job,
          async () => {
            runnerStarted = true;
            return {
              exitStatus: 0,
              threadId: 'thread-disable-heartbeat',
              turnId: 'turn-disable-heartbeat',
              summary: 'completed with heartbeat disabled',
              payload: { ok: true },
              rendered: 'completed with heartbeat disabled'
            };
          },
          { logFile: job.logFile }
        );
        const jobFile = resolveJobFile(cwd, job.id);
        const stored = readJobFile(jobFile);

        console.log(JSON.stringify({
          runnerStarted,
          executionStatus: execution.exitStatus,
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          storedStatus: stored.status,
          heartbeatAtMs: stored.heartbeatAtMs ?? null
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["runnerStarted"] is True
    assert payload["executionStatus"] == 0
    assert payload["jobFileExists"] is True
    assert payload["storedStatus"] == "completed"
    assert payload["heartbeatAtMs"] is None
    assert payload["jobs"][0]["status"] == "completed"


def test_codex_run_tracked_job_with_heartbeat_disabled_still_checks_session_end_before_runner(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';

        const cwd = process.argv[1];
        process.env.CODEX_FOR_CLAUDE_DISABLE_HEARTBEAT = '1';
        const originalRenameSync = fs.renameSync;
        let injected = false;
        fs.renameSync = function patchedRenameSync(from, to) {
          originalRenameSync.call(this, from, to);
          if (injected || !String(to).endsWith('/heartbeat-disabled-start-race.json')) {
            return;
          }
          try {
            const stored = JSON.parse(fs.readFileSync(to, 'utf8'));
            if (stored.status !== 'running') {
              return;
            }
            injected = true;
            const stateFile = String(to).replace(/\\/jobs\\/heartbeat-disabled-start-race\\.json$/, '/state.json');
            const state = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
            state.endedSessions = [...(state.endedSessions || []), 'session-heartbeat-disabled-start-race'];
            state.jobs = state.jobs.filter((job) => job.id !== 'heartbeat-disabled-start-race');
            fs.writeFileSync(stateFile, `${JSON.stringify(state, null, 2)}\\n`, 'utf8');
          } catch {
            // Non-target rename calls are irrelevant for this race injection.
          }
        };

        const tracked = await import('./plugins/codex/scripts/lib/tracked-jobs.mjs');
        const state = await import('./plugins/codex/scripts/lib/state.mjs');
        let runnerStarted = false;
        let errorMessage = '';
        const job = {
          id: 'heartbeat-disabled-start-race',
          status: 'queued',
          kind: 'task',
          title: 'Heartbeat disabled start race',
          workspaceRoot: cwd,
          sessionId: 'session-heartbeat-disabled-start-race',
          phase: 'queued',
          pid: null,
          logFile: state.resolveJobLogFile(cwd, 'heartbeat-disabled-start-race')
        };
        fs.writeFileSync(job.logFile, 'heartbeat disabled start log\\n', 'utf8');
        try {
          await tracked.runTrackedJob(
            job,
            async () => {
              runnerStarted = true;
              return {
                exitStatus: 0,
                threadId: 'thread-heartbeat-disabled-start-race',
                turnId: 'turn-heartbeat-disabled-start-race',
                summary: 'should not run',
                payload: {},
                rendered: 'should not render'
              };
            },
            { logFile: job.logFile }
          );
        } catch (error) {
          errorMessage = error instanceof Error ? error.message : String(error);
        }
        const jobFile = state.resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          injected,
          runnerStarted,
          errorMessage,
          jobs: state.listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(job.logFile)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["injected"] is True
    assert payload["runnerStarted"] is False
    assert "ended before job heartbeat-disabled-start-race could run" in payload["errorMessage"]
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert payload["logFileExists"] is False


def test_codex_run_tracked_job_prerun_session_end_removes_options_log(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          runTrackedJob
        } from './plugins/codex/scripts/lib/tracked-jobs.mjs';
        import {
          listJobs,
          markSessionEnded,
          resolveJobFile,
          resolveJobLogFile,
          updateState
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'prerun-ended-session-options-log',
          status: 'queued',
          kind: 'task',
          title: 'Prerun ended session options log',
          workspaceRoot: cwd,
          sessionId: 'session-prerun-ended-options-log',
          phase: 'queued',
          pid: null
        };
        const logFile = resolveJobLogFile(cwd, job.id);
        fs.writeFileSync(logFile, 'secret-before-run\\n', 'utf8');
        updateState(cwd, (state) => {
          markSessionEnded(state, 'session-prerun-ended-options-log');
        });

        let runnerStarted = false;
        let errorMessage = '';
        try {
          await runTrackedJob(
            job,
            async () => {
              runnerStarted = true;
              return {
                exitStatus: 0,
                threadId: 'thread-prerun',
                turnId: 'turn-prerun',
                summary: 'should not run',
                payload: {},
                rendered: 'should not render'
              };
            },
            { logFile }
          );
        } catch (error) {
          errorMessage = error instanceof Error ? error.message : String(error);
        }
        const jobFile = resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          runnerStarted,
          errorMessage,
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(logFile),
          logFileText: fs.existsSync(logFile) ? fs.readFileSync(logFile, 'utf8') : ''
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["runnerStarted"] is False
    assert "ended before job prerun-ended-session-options-log could run" in payload["errorMessage"]
    assert payload["jobs"] == []
    assert payload["jobFileExists"] is False
    assert payload["logFileExists"] is False
    assert "secret-before-run" not in payload["logFileText"]


def test_codex_companion_publishes_background_and_cancel_state_before_job_file_writes():
    source = read_text(PLUGIN / "scripts" / "codex-companion.mjs")
    failure = js_function_body(source, "recordBackgroundLaunchFailure")
    enqueue = js_function_body(source, "enqueueBackgroundTask")
    cancel = js_function_body(source, "handleCancel")
    run_tracked = js_function_body(read_text(PLUGIN / "scripts" / "lib" / "tracked-jobs.mjs"), "runTrackedJob")

    assert failure.index("upsertJob(job.workspaceRoot") < failure.index("writeJobFile(job.workspaceRoot, job.id, failedRecord)")
    assert "if (!upsertJob(job.workspaceRoot" in failure
    assert failure.index("if (!upsertJob(job.workspaceRoot") < failure.index("writeJobFile(job.workspaceRoot, job.id, failedRecord)")
    assert "const failedJobFile = writeJobFile(job.workspaceRoot, job.id, failedRecord)" in failure
    assert "if (!failedJobFile)" in failure
    assert enqueue.index("upsertJob(job.workspaceRoot", enqueue.index("const queuedRecord")) < enqueue.index("writeJobFile(job.workspaceRoot, job.id, queuedRecord)")
    assert enqueue.index("upsertJob(job.workspaceRoot", enqueue.index("const spawnedRecord")) < enqueue.index("writeJobFile(job.workspaceRoot, job.id, spawnedRecord)")
    assert "const queuedStateApplied = upsertJob(job.workspaceRoot" in enqueue
    assert "if (!queuedStateApplied)" in enqueue
    assert "const queuedJobFile = writeJobFile(job.workspaceRoot, job.id, queuedRecord)" in enqueue
    assert "if (!queuedJobFile)" in enqueue
    assert "const spawnedStateApplied = upsertJob(job.workspaceRoot" in enqueue
    assert "if (!spawnedStateApplied)" in enqueue
    assert "const spawnedJobFile = writeJobFile(job.workspaceRoot, job.id, spawnedRecord)" in enqueue
    assert "if (!spawnedJobFile)" in enqueue
    assert cancel.index("upsertJob(workspaceRoot") < cancel.index("writeJobFile(workspaceRoot, job.id")
    assert "if (!upsertJob(workspaceRoot" in cancel
    assert "sessionId: job.sessionId" in cancel
    assert "const cancelledJobFile = writeJobFile(workspaceRoot, job.id" in cancel
    assert "if (!cancelledJobFile)" in cancel
    assert "const runningJobFile = writeJobFile(job.workspaceRoot, job.id, runningRecord)" in run_tracked
    assert "if (!runningJobFile)" in run_tracked
    assert "const failedJobFile = writeJobFile(job.workspaceRoot, job.id, failedRecord)" in run_tracked
    assert "if (!failedJobFile)" in run_tracked


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


def test_codex_status_includes_pruned_active_sidecar_without_private_payload(tmp_path):
    env = companion_env(tmp_path, fake_cli_dir(tmp_path, {"plugins": []}))
    run_node_script(
        """
        import fs from 'node:fs';
        import {
          resolveJobLogFile,
          saveState,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const active = {
          id: 'status-pruned-active-sidecar',
          status: 'running',
          phase: 'running',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Pruned active sidecar',
          summary: 'visible active sidecar',
          workspaceRoot: cwd,
          sessionId: 'session-status-pruned-active',
          pid: process.pid,
          request: { secret: 'PRIVATE_REQUEST_SECRET' },
          result: { secret: 'PRIVATE_RESULT_SECRET' },
          rendered: 'PRIVATE_RENDERED_SECRET',
          backgroundLeaseId: 'PRIVATE_LEASE_SECRET',
          logFile: resolveJobLogFile(cwd, 'status-pruned-active-sidecar'),
          updatedAt: '2000-01-01T00:00:00.000Z',
          heartbeatAtMs: Date.now(),
          heartbeatAt: new Date().toISOString()
        };
        writeJobFile(cwd, active.id, active);
        fs.writeFileSync(active.logFile, 'active sidecar log\\n', 'utf8');
        const newerJobs = Array.from({ length: 51 }, (_, index) => ({
          id: `newer-completed-${index}`,
          status: 'completed',
          workspaceRoot: cwd,
          updatedAt: new Date(Date.now() + index).toISOString()
        }));
        saveState(cwd, { jobs: [active, ...newerJobs] });
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    result = run_companion(["status", "--cwd", str(tmp_path), "--json", "--all"], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    job = next(item for item in payload["running"] if item["id"] == "status-pruned-active-sidecar")
    text = json.dumps(job)
    assert job["status"] == "running"
    assert job["liveness"]["state"] in {"healthy", "suspect", "lost", "unknown"}
    assert "request" not in job
    assert "result" not in job
    assert "rendered" not in job
    assert "backgroundLeaseId" not in job
    assert "PRIVATE_REQUEST_SECRET" not in text
    assert "PRIVATE_RESULT_SECRET" not in text
    assert "PRIVATE_RENDERED_SECRET" not in text
    assert "PRIVATE_LEASE_SECRET" not in text


def test_codex_status_uses_active_sidecar_when_partial_shared_progress_row_exists(tmp_path):
    env = companion_env(tmp_path, fake_cli_dir(tmp_path, {"plugins": []}))
    run_node_script(
        """
        import fs from 'node:fs';
        import {
          resolveJobLogFile,
          upsertJob,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'status-partial-progress-sidecar',
          status: 'running',
          phase: 'starting',
          kind: 'task',
          title: 'Partial progress sidecar',
          workspaceRoot: cwd,
          sessionId: 'session-status-partial-progress',
          pid: process.pid,
          request: { secret: 'PRIVATE_PARTIAL_REQUEST' },
          rendered: 'PRIVATE_PARTIAL_RENDERED',
          logFile: resolveJobLogFile(cwd, 'status-partial-progress-sidecar'),
          updatedAt: new Date().toISOString()
        };
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, 'partial progress log\\n', 'utf8');
        upsertJob(cwd, {
          id: job.id,
          phase: 'running',
          threadId: 'thread-partial-progress'
        });
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    result = run_companion(["status", "--cwd", str(tmp_path), "--json", "--all"], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    job = next(item for item in payload["running"] if item["id"] == "status-partial-progress-sidecar")
    text = json.dumps(job)
    assert job["status"] == "running"
    assert job["sessionId"] == "session-status-partial-progress"
    assert job["threadId"] == "thread-partial-progress"
    assert "request" not in job
    assert "rendered" not in job
    assert "PRIVATE_PARTIAL_REQUEST" not in text
    assert "PRIVATE_PARTIAL_RENDERED" not in text


def test_codex_status_omits_tombstoned_sidecar_only_active_job(tmp_path):
    env = companion_env(tmp_path, fake_cli_dir(tmp_path, {"plugins": []}))
    run_node_script(
        """
        import fs from 'node:fs';
        import {
          markSessionEnded,
          resolveJobLogFile,
          updateState,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        process.env.CODEX_FOR_CLAUDE_SKIP_STATE_PRUNE = '1';
        const job = {
          id: 'status-tombstoned-sidecar-only',
          status: 'running',
          phase: 'running',
          kind: 'task',
          title: 'Tombstoned sidecar only',
          workspaceRoot: cwd,
          sessionId: 'session-status-tombstoned-sidecar',
          request: { secret: 'PRIVATE_TOMBSTONED_REQUEST' },
          logFile: resolveJobLogFile(cwd, 'status-tombstoned-sidecar-only'),
          updatedAt: new Date().toISOString()
        };
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, '[2000-01-01T00:00:00.000Z] PRIVATE_TOMBSTONED_LOG\\n', 'utf8');
        updateState(cwd, (state) => {
          markSessionEnded(state, 'session-status-tombstoned-sidecar');
          state.jobs = state.jobs.filter((item) => item.id !== job.id);
        });
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    result = run_companion(["status", "--cwd", str(tmp_path), "--json", "--all"], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    text = json.dumps(payload)
    assert all(job["id"] != "status-tombstoned-sidecar-only" for job in payload["running"])
    assert "PRIVATE_TOMBSTONED_REQUEST" not in text
    assert "PRIVATE_TOMBSTONED_LOG" not in text


def test_codex_status_rechecks_tombstone_while_merging_sidecars(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          markSessionEnded,
          resolveJobLogFile,
          resolveJobsDir,
          updateState,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'status-sidecar-merge-race',
          status: 'running',
          phase: 'running',
          kind: 'task',
          title: 'Status sidecar merge race',
          workspaceRoot: cwd,
          sessionId: 'session-status-sidecar-merge-race',
          request: { secret: 'PRIVATE_MERGE_RACE_REQUEST' },
          logFile: resolveJobLogFile(cwd, 'status-sidecar-merge-race'),
          updatedAt: new Date().toISOString()
        };
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, '[2000-01-01T00:00:00.000Z] PRIVATE_MERGE_RACE_LOG\\n', 'utf8');

        const jobsDir = resolveJobsDir(cwd);
        const originalReaddirSync = fs.readdirSync;
        let injected = false;
        fs.readdirSync = function patchedReaddirSync(dirPath, ...args) {
          if (!injected && String(dirPath) === jobsDir) {
            injected = true;
            updateState(cwd, (state) => {
              markSessionEnded(state, 'session-status-sidecar-merge-race');
              state.jobs = state.jobs.filter((item) => item.id !== job.id);
            });
          }
          return originalReaddirSync.call(this, dirPath, ...args);
        };

        const { buildStatusSnapshot } = await import('./plugins/codex/scripts/lib/job-control.mjs');
        const snapshot = buildStatusSnapshot(cwd, { all: true });
        fs.readdirSync = originalReaddirSync;
        console.log(JSON.stringify({ injected, snapshot }));
        """,
        args=[str(tmp_path)],
    )

    text = json.dumps(payload["snapshot"])
    assert payload["injected"] is True
    assert all(job["id"] != "status-sidecar-merge-race" for job in payload["snapshot"]["running"])
    assert "PRIVATE_MERGE_RACE_REQUEST" not in text
    assert "PRIVATE_MERGE_RACE_LOG" not in text


def test_codex_single_status_filters_current_session_unless_all(tmp_path):
    env = companion_env(tmp_path, fake_cli_dir(tmp_path, {"plugins": []}))
    env["CODEX_COMPANION_SESSION_ID"] = "session-a"
    run_node_script(
        """
        import { upsertJob, writeJobFile } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        const sameSession = {
          id: 'same-session-job',
          status: 'running',
          phase: 'running',
          workspaceRoot: cwd,
          sessionId: 'session-a',
          updatedAt: new Date().toISOString(),
          pid: null
        };
        const foreignSession = {
          id: 'foreign-session-job',
          status: 'running',
          phase: 'running',
          workspaceRoot: cwd,
          sessionId: 'session-b',
          updatedAt: new Date().toISOString(),
          pid: null
        };
        upsertJob(cwd, sameSession);
        writeJobFile(cwd, sameSession.id, sameSession);
        upsertJob(cwd, foreignSession);
        writeJobFile(cwd, foreignSession.id, foreignSession);
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    scoped = run_companion(["status", "foreign-session-job", "--cwd", str(tmp_path), "--json"], cwd=tmp_path, env=env)
    assert scoped.returncode == 1
    assert "No job found" in scoped.stderr

    all_sessions = run_companion(
        ["status", "foreign-session-job", "--cwd", str(tmp_path), "--json", "--all"],
        cwd=tmp_path,
        env=env,
    )
    assert all_sessions.returncode == 0, all_sessions.stderr
    payload = json.loads(all_sessions.stdout)
    assert payload["job"]["id"] == "foreign-session-job"
    assert payload["job"]["sessionId"] == "session-b"


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


def test_codex_status_text_includes_liveness_for_list_and_single_job(tmp_path):
    env = companion_env(tmp_path, fake_cli_dir(tmp_path, {"plugins": []}))
    run_node_script(
        """
        import { JOB_LOST_AFTER_MS } from './plugins/codex/scripts/lib/job-lifecycle.mjs';
        import { upsertJob, writeJobFile } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        const oldMs = Date.now() - JOB_LOST_AFTER_MS - 1000;
        const old = new Date(oldMs).toISOString();
        const job = {
          id: 'text-live-state',
          status: 'running',
          phase: 'running',
          kind: 'task',
          title: 'Text live state',
          workspaceRoot: cwd,
          updatedAt: old,
          heartbeatAtMs: oldMs,
          heartbeat: old,
          pid: null
        };
        upsertJob(cwd, job);
        writeJobFile(cwd, job.id, job);
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )
    list_result = run_companion(["status", "--cwd", str(tmp_path), "--all"], cwd=tmp_path, env=env)
    assert list_result.returncode == 0, list_result.stderr
    assert "| Job | Kind | Status | Phase | Liveness |" in list_result.stdout
    assert "lost (heartbeat-lost)" in list_result.stdout

    single_result = run_companion(["status", "text-live-state", "--cwd", str(tmp_path)], cwd=tmp_path, env=env)
    assert single_result.returncode == 0, single_result.stderr
    assert "Liveness: lost (heartbeat-lost)" in single_result.stdout


def test_codex_status_liveness_ignores_mismatched_or_malformed_job_files(tmp_path):
    source = read_text(PLUGIN / "scripts" / "lib" / "job-control.mjs")
    latest_body = js_function_body(source, "latestJobForLiveness")
    assert "const root = job.workspaceRoot ?? workspaceRoot" in latest_body
    assert "catch" in latest_body
    assert "stored?.id !== job.id" in latest_body
    env = companion_env(tmp_path, fake_cli_dir(tmp_path, {"plugins": []}))
    run_node_script(
        """
        import fs from 'node:fs';
        import { JOB_LOST_AFTER_MS } from './plugins/codex/scripts/lib/job-lifecycle.mjs';
        import { upsertJob, resolveJobFile } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        const old = new Date(Date.now() - JOB_LOST_AFTER_MS - 1000).toISOString();
        const job = {
          id: 'mismatched-liveness',
          status: 'running',
          phase: 'running',
          workspaceRoot: cwd,
          updatedAt: old,
          pid: null
        };
        const malformed = {
          ...job,
          id: 'malformed-liveness'
        };
        upsertJob(cwd, job);
        upsertJob(cwd, malformed);
        fs.writeFileSync(resolveJobFile(cwd, job.id), JSON.stringify({
          id: 'other-job',
          status: 'running',
          heartbeatAtMs: Date.now(),
          heartbeat: new Date().toISOString()
        }));
        fs.writeFileSync(resolveJobFile(cwd, malformed.id), '{not valid json');
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )
    result = run_companion(["status", "--cwd", str(tmp_path), "--json", "--all"], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    job = next(item for item in payload["running"] if item["id"] == "mismatched-liveness")
    assert job["liveness"]["state"] == "lost"
    assert job["liveness"]["reason"] == "heartbeat-lost"
    malformed = next(item for item in payload["running"] if item["id"] == "malformed-liveness")
    assert malformed["liveness"]["state"] == "lost"
    assert malformed["liveness"]["reason"] == "heartbeat-lost"


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
