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
