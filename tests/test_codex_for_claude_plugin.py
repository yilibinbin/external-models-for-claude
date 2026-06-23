import json
import os
import pathlib
import re
import shutil
import subprocess

import pytest

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
    "github-actions.md",
    "multi-review.md",
    "rescue.md",
    "result.md",
    "review.md",
    "setup.md",
    "status.md",
]
TEXT_EXTENSIONS = {".md", ".mdx", ".mjs", ".ts", ".txt", ".json", ".yaml", ".yml"}


def read_json(path):
    return json.loads(path.read_text(encoding="utf8"))


def read_text(path):
    return path.read_text(encoding="utf8")


def provider_isolation_text():
    parts = [
        read_text(PLUGIN / "README.md"),
        read_text(PLUGIN / "FORK_NOTICE.md"),
        read_text(PLUGIN / "CHANGELOG.md"),
    ]
    roots = [
        PLUGIN / "scripts",
        PLUGIN / "agents",
        PLUGIN / "commands",
        PLUGIN / "skills",
        PLUGIN / "prompts",
        PLUGIN / "templates",
    ]
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in TEXT_EXTENSIONS:
                parts.append(read_text(path))
    return "\n".join(parts)


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


def run_node(script, args=None, env=None, timeout=30, cwd=ROOT):
    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    return subprocess.run(
        [NODE, str(script), *(args or [])],
        cwd=cwd,
        env=command_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
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


def fake_codex_app_server_dir(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "fake-codex-app-server.mjs").write_text(
        """
import readline from 'node:readline';
const threadId = 'thread-stop-gate';
const turnId = 'turn-stop-gate';
const rl = readline.createInterface({ input: process.stdin });
function send(message) {
  console.log(JSON.stringify(message));
}
rl.on('line', (line) => {
  if (!line.trim()) return;
  const message = JSON.parse(line);
  if (message.method === 'initialize') {
    send({ id: message.id, result: {} });
  } else if (message.method === 'thread/start') {
    send({ id: message.id, result: { thread: { id: threadId } } });
  } else if (message.method === 'thread/name/set') {
    send({ id: message.id, result: {} });
  } else if (message.method === 'turn/start') {
    send({
      method: 'item/completed',
      params: {
        threadId,
        item: {
          type: 'agentMessage',
          phase: 'final_answer',
          text: process.env.CODEX_TEST_STOP_OUTPUT || 'BLOCK: fake stop issue'
        }
      }
    });
    send({ method: 'turn/completed', params: { threadId, turn: { id: turnId, status: 'completed' } } });
    send({ id: message.id, result: { turn: { id: turnId, status: 'completed' } } });
  } else {
    send({ id: message.id, result: {} });
  }
});
""",
        encoding="utf8",
    )
    write_executable(
        bin_dir / "codex",
        """#!/bin/sh
if [ "$1" = "--version" ]; then
  printf 'codex 1.0.0\\n'
  exit 0
fi
if [ "$1" = "app-server" ] && [ "$2" = "--help" ]; then
  printf 'codex app-server help\\n'
  exit 0
fi
if [ "$1" = "app-server" ]; then
  exec node "$(dirname "$0")/fake-codex-app-server.mjs"
fi
printf 'unexpected fake codex args: %s\\n' "$*" >&2
exit 1
""",
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
    assert "Local extended version: 1.1.0-fh.2" in notices
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


def test_codex_command_surface_includes_new_commands():
    commands = {path.name for path in (PLUGIN / "commands").glob("*.md")}
    expected = {
        "adversarial-review.md",
        "cancel.md",
        "doctor.md",
        "github-actions.md",
        "multi-review.md",
        "rescue.md",
        "result.md",
        "review.md",
        "setup.md",
        "status.md",
    }
    assert commands == expected


def test_codex_print_usage_mentions_new_commands():
    companion = read_text(PLUGIN / "scripts" / "codex-companion.mjs")
    usage_body = js_function_body(companion, "printUsage")
    for command in ["doctor", "github-actions", "multi-review", "release-check"]:
        assert command in usage_body


def test_codex_shipped_text_has_no_external_provider_leakage():
    text = provider_isolation_text()
    assert "GEMINI_FOR_CODEX" not in text
    assert "ANTIGRAVITY_FOR_CODEX" not in text
    assert "GEMINI_FOR_CLAUDE" not in text
    assert "ANTIGRAVITY_FOR_CLAUDE" not in text
    assert "model-provider gemini" not in text.lower()
    assert "model-provider claude" not in text.lower()


def test_codex_source_does_not_import_sibling_provider_plugins():
    roots = [
        PLUGIN / "scripts",
        PLUGIN / "agents",
        PLUGIN / "commands",
        PLUGIN / "skills",
        PLUGIN / "prompts",
        PLUGIN / "templates",
    ]
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in TEXT_EXTENSIONS:
                text = read_text(path)
                assert "../gemini-for-claude" not in text
                assert "../antigravity-for-claude" not in text
                assert "plugins/gemini-for-claude" not in text
                assert "plugins/antigravity-for-claude" not in text


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


def test_codex_command_policy_short_value_hint_does_not_suggest_inline_equals():
    script = """
        import { parseStrictCommandInput } from './plugins/codex/scripts/lib/command-policy.mjs';
        try {
          parseStrictCommandInput('review', ['-m', '--json'], {
            valueOptions: ['model'],
            booleanOptions: ['json'],
            aliasMap: { m: 'model' }
          });
        } catch (error) {
          console.log(JSON.stringify({ message: error.message }));
        }
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
    assert "-m requires a separate value token" in payload["message"]
    assert "-m=--json" not in payload["message"]


def test_codex_new_commands_use_strict_command_parser():
    companion = read_text(PLUGIN / "scripts" / "codex-companion.mjs")
    args_module = read_text(PLUGIN / "scripts" / "lib" / "args.mjs")
    command_policy = read_text(PLUGIN / "scripts" / "lib" / "command-policy.mjs")

    assert "export function normalizeArgv" in args_module
    assert "normalizeArgv" in companion
    assert 'from "./lib/args.mjs"' in companion
    assert 'from "./args.mjs"' in command_policy
    assert "function normalizeArgv" not in companion

    for name in ["handleSetup", "handleDoctor", "handleReleaseCheck", "handleGithubActions"]:
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


def test_codex_adversarial_review_focus_text_reaches_strict_parser():
    script = (
        "const p = await import('./plugins/codex/scripts/lib/command-policy.mjs');"
        "const parsed = p.parseStrictCommandInput('adversarial-review', ['--base','main','--','focus','on','--flag-like','text'], {valueOptions:['base','scope','model','cwd','quality'], booleanOptions:['json','background','wait'], aliasMap:{C:'cwd',m:'model'}});"
        "process.stdout.write(JSON.stringify(parsed));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["options"]["base"] == "main"
    assert payload["positionals"] == ["focus", "on", "--flag-like", "text"]


def test_codex_review_wrapper_tokenization_contract_preserves_focus_text():
    script = (
        "const p = await import('./plugins/codex/scripts/lib/command-policy.mjs');"
        "const parsed = p.parseStrictCommandInput('review', ['--base','main','--','focus','on','quoted phrase','--flag-like','text'], {valueOptions:['base','scope','model','cwd','quality'], booleanOptions:['json','background','wait'], aliasMap:{C:'cwd',m:'model'}});"
        "process.stdout.write(JSON.stringify(parsed));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["options"]["base"] == "main"
    assert payload["positionals"] == ["focus", "on", "quoted phrase", "--flag-like", "text"]


def test_codex_task_options_must_precede_prompt_in_prompt_first_mode():
    script = (
        "const p = await import('./plugins/codex/scripts/lib/command-policy.mjs');"
        "const allowed = {valueOptions:['model','effort','cwd','prompt-file','quality'], booleanOptions:['json','write','resume-last','resume','fresh','background'], aliasMap:{C:'cwd', m:'model'}, promptAfterFirstPositional:true};"
        "const before = p.parseStrictCommandInput('task', ['--model','gpt-5','fix','it'], allowed);"
        "const after = p.parseStrictCommandInput('task', ['fix','it','--model','gpt-5'], allowed);"
        "process.stdout.write(JSON.stringify({before, after}));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["before"]["options"]["model"] == "gpt-5"
    assert payload["before"]["positionals"] == ["fix", "it"]
    assert payload["after"]["options"].get("model") is None
    assert payload["after"]["positionals"] == ["fix", "it", "--model", "gpt-5"]


def test_codex_quality_legacy_commands_reject_unknown_flags():
    for args in [
        ["review", "--qualiy", "max"],
        ["adversarial-review", "--qualiy", "max"],
        ["task", "--qualiy", "max", "inspect"],
    ]:
        result = run_node("plugins/codex/scripts/codex-companion.mjs", args, timeout=10)
        assert result.returncode == 1
        assert "Unsupported option" in result.stderr


def test_codex_review_and_task_use_strict_command_parser():
    companion = read_text(PLUGIN / "scripts" / "codex-companion.mjs")
    for name in ["handleTask", "handleReviewCommand"]:
        body = js_function_body(companion, name)
        assert "parseStrictCommandInput(" in body
        assert "parseCommandInput(" not in body
        assert "parseArgs(" not in body


def test_codex_strict_parser_preserves_cwd_and_model_aliases_for_migrated_commands():
    companion = read_text(PLUGIN / "scripts" / "codex-companion.mjs")
    for name in ["handleTask", "handleReviewCommand", "handleMultiReview"]:
        body = js_function_body(companion, name)
        assert 'C: "cwd"' in body
        assert 'm: "model"' in body
    setup_body = js_function_body(companion, "handleSetup")
    assert 'C: "cwd"' in setup_body


def test_codex_task_prompt_can_intentionally_start_with_flag_after_terminator():
    script = (
        "const p = await import('./plugins/codex/scripts/lib/command-policy.mjs');"
        "const parsed = p.parseStrictCommandInput('task', ['--','--foo','is','broken'], {valueOptions:['model','effort','cwd','prompt-file','quality'], booleanOptions:['json','write','resume-last','resume','fresh','background'], aliasMap:{C:'cwd', m:'model'}, promptAfterFirstPositional:true});"
        "process.stdout.write(JSON.stringify(parsed.positionals));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["--foo", "is", "broken"]


def test_codex_task_prompt_keeps_option_like_tokens_after_first_positional():
    script = (
        "const p = await import('./plugins/codex/scripts/lib/command-policy.mjs');"
        "const parsed = p.parseStrictCommandInput('task', ['fix', '--foo', 'regression'], {valueOptions:['model','effort','cwd','prompt-file','quality'], booleanOptions:['json','write','resume-last','resume','fresh','background'], aliasMap:{C:'cwd', m:'model'}, promptAfterFirstPositional:true});"
        "process.stdout.write(JSON.stringify(parsed.positionals));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["fix", "--foo", "regression"]


def test_codex_rescue_task_callers_use_terminator_for_generated_prompts():
    rescue_command = read_text(PLUGIN / "commands" / "rescue.md")
    rescue_agent = read_text(PLUGIN / "agents" / "codex-rescue.md")
    rescue_command_runtime_line = next(line for line in rescue_command.splitlines() if "runtime flags such as" in line)
    rescue_agent_runtime_line = next(line for line in rescue_agent.splitlines() if "runtime flags such as" in line)
    assert "task ... -- <task text>" in rescue_command
    assert "-- before the forwarded task text" in rescue_command
    assert "`--wait` is a Claude-side foreground selection hint; do not forward it to `task`." in rescue_command
    assert "`--wait`" not in rescue_command_runtime_line
    assert "task ... -- <task text>" in rescue_agent
    assert "-- before the forwarded task text" in rescue_agent
    assert "`--wait` is a Claude-side foreground selection hint; do not forward it to `task`." in rescue_agent
    assert "`--wait`" not in rescue_agent_runtime_line


def test_codex_stop_hook_task_invocation_uses_terminator_before_task_strict_parser_lands():
    hook_source = read_text(PLUGIN / "scripts" / "stop-review-gate-hook.mjs")
    assert '[scriptPath, "task", "--json", "--", prompt]' in hook_source
    assert '[scriptPath, "task", "--json", prompt]' not in hook_source


def test_codex_review_command_wrappers_do_not_interpolate_raw_arguments():
    for name in ["review.md", "adversarial-review.md"]:
        text = read_text(PLUGIN / "commands" / name)
        assert "$ARGUMENTS" in text
        assert '"$ARGUMENTS"' not in text
        assert "Do not interpolate `$ARGUMENTS` into Bash" in text
        assert "Parse this text into independent argv tokens before invoking the companion" in text
        assert "Append parsed user arguments as separately quoted argv tokens" in text


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


def test_codex_github_actions_command_does_not_interpolate_raw_arguments():
    text = read_text(PLUGIN / "commands" / "github-actions.md")

    assert "disable-model-invocation" not in text
    assert "$ARGUMENTS" in text
    for block in fenced_bash_blocks(text):
        assert "$ARGUMENTS" not in block
    assert 'node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" github-actions render' in text
    assert 'node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" github-actions validate' in text
    assert 'node "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" github-actions init' in text
    assert "github-actions render --ref v0.2.0 --json" not in text
    assert "github-actions validate --ref v0.2.0 --json" in text


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


def test_codex_machine_path_redaction_runtime_uses_single_contract():
    leaked = "bad:/Users/fanghao/private.sock and file:///private/var/folders/demo/socket"
    script = """
        import { redactMachinePaths } from './plugins/codex/scripts/lib/path-hygiene.mjs';
        console.log(redactMachinePaths(process.argv[1]));
    """
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", script, leaked],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "/Users/fanghao" not in result.stdout
    assert "/private/var/folders" not in result.stdout
    assert "<local-path>" in result.stdout


def test_codex_machine_path_pattern_source_is_single_contract():
    path_hygiene = read_text(PLUGIN / "scripts" / "lib" / "path-hygiene.mjs")
    assert "MACHINE_PATH_PATTERN_SOURCE" in path_hygiene
    assert "new RegExp(MACHINE_PATH_PATTERN_SOURCE" in path_hygiene
    assert "function hasMachinePath" in path_hygiene
    assert "function redactMachinePaths" in path_hygiene

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
        "reason": "lease command mismatch",
    }


def test_codex_resource_governor_verify_expected_parent_pid_uses_owner(tmp_path):
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
        const missingOwner = verifyResourceLease(lease.lease.id, 'stop-gate', { env: process.env, expectedParentPid: process.pid });
        const deadOwner = JSON.parse(fs.readFileSync(file, 'utf8'));
        deadOwner.ownerPid = 99999999;
        deadOwner.createdAtMs = Date.now();
        fs.writeFileSync(file, `${JSON.stringify(deadOwner, null, 2)}\\n`);
        const deadParent = verifyResourceLease(lease.lease.id, 'stop-gate', { env: process.env, expectedParentPid: 99999999 });
        lease.release();
        console.log(JSON.stringify({
          ownerMatchOk: ownerMatch.ok,
          mismatchOk: mismatch.ok,
          mismatchReason: mismatch.reason,
          missingOwnerOk: missingOwner.ok,
          missingOwnerReason: missingOwner.reason,
          deadParentOk: deadParent.ok,
          deadParentReason: deadParent.reason
        }));
        """,
        env=governor_env(tmp_path),
    )
    assert payload["ownerMatchOk"] is True
    assert payload["mismatchOk"] is False
    assert payload["mismatchReason"] == "lease parent mismatch"
    assert payload["missingOwnerOk"] is False
    assert payload["missingOwnerReason"] == "lease parent mismatch"
    assert payload["deadParentOk"] is False
    assert payload["deadParentReason"] == "lease parent not alive"


def test_codex_stop_child_parent_lease_verification_rejects_stale_or_dead_parent(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import path from 'node:path';
        import { acquireResourceLease, resourceLockRoot, verifyResourceLease } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const lease = acquireResourceLease('stop-gate', { env: process.env, command: 'stop-review-gate' });
        if (!lease.ok) throw new Error('lease failed');
        const file = path.join(resourceLockRoot(process.env), `${lease.lease.id}.json`);
        const original = JSON.parse(fs.readFileSync(file, 'utf8'));
        fs.writeFileSync(file, `${JSON.stringify({ ...original, createdAtMs: Date.now() - 25 * 60 * 60 * 1000 }, null, 2)}\\n`);
        const stale = verifyResourceLease(lease.lease.id, 'stop-gate', { env: process.env, expectedParentPid: process.pid, expectedCommand: 'stop-review-gate' });
        fs.writeFileSync(file, `${JSON.stringify({ ...original, ownerPid: 99999999, createdAtMs: Date.now() }, null, 2)}\\n`);
        const dead = verifyResourceLease(lease.lease.id, 'stop-gate', { env: process.env, expectedParentPid: 99999999, expectedCommand: 'stop-review-gate' });
        lease.release();
        console.log(JSON.stringify({ stale: stale.ok, staleReason: stale.reason, dead: dead.ok, deadReason: dead.reason }));
        """,
        env=governor_env(tmp_path),
    )
    assert payload == {
        "stale": False,
        "staleReason": "lease stale",
        "dead": False,
        "deadReason": "lease parent not alive",
    }


def test_codex_stop_child_parent_lease_verification_accepts_spawned_child_ppid(tmp_path):
    payload = run_node_script(
        """
        import { spawnSync } from 'node:child_process';
        import { acquireResourceLease } from './plugins/codex/scripts/lib/resource-governor.mjs';
        const lease = acquireResourceLease('stop-gate', { env: process.env, command: 'stop-review-gate' });
        if (!lease.ok) throw new Error('parent lease failed');
        const child = spawnSync(process.execPath, ['--input-type=module', '-e', `
          import { verifyResourceLease } from './plugins/codex/scripts/lib/resource-governor.mjs';
          const verification = verifyResourceLease(process.env.CODEX_FOR_CLAUDE_PARENT_STOP_GATE_LEASE_ID, 'stop-gate', { env: process.env, expectedParentPid: process.ppid, expectedCommand: 'stop-review-gate' });
          process.stdout.write(JSON.stringify({ ok: verification.ok, reason: verification.reason || '' }));
        `], {
          cwd: process.cwd(),
          env: { ...process.env, CODEX_FOR_CLAUDE_PARENT_STOP_GATE_LEASE_ID: lease.lease.id },
          encoding: 'utf8'
        });
        lease.release();
        if (child.status !== 0) {
          process.stderr.write(child.stderr);
          process.exit(child.status || 1);
        }
        console.log(child.stdout);
        """,
        env=governor_env(tmp_path),
    )
    assert payload == {"ok": True, "reason": ""}


def test_codex_stop_gate_task_invocation_uses_terminator():
    hook_source = read_text(PLUGIN / "scripts" / "stop-review-gate-hook.mjs")
    assert '[scriptPath, "task", "--json", "--", prompt]' in hook_source
    assert '[scriptPath, "task", "--json", prompt]' not in hook_source


def test_codex_internal_task_callers_use_terminator_for_generated_prompts():
    hook_source = read_text(PLUGIN / "scripts" / "stop-review-gate-hook.mjs")
    rescue_command = read_text(PLUGIN / "commands" / "rescue.md")
    rescue_agent = read_text(PLUGIN / "agents" / "codex-rescue.md")
    assert '[scriptPath, "task", "--json", "--", prompt]' in hook_source
    assert '[scriptPath, "task", "--json", prompt]' not in hook_source
    assert "task ... -- <task text>" in rescue_command
    assert "-- before the forwarded task text" in rescue_command
    assert "task ... -- <task text>" in rescue_agent
    assert "-- before the forwarded task text" in rescue_agent


def test_codex_stop_gate_env_off_allows_stop(tmp_path):
    result = subprocess.run(
        [NODE, str(PLUGIN / "scripts" / "stop-review-gate-hook.mjs")],
        cwd=tmp_path,
        env={
            **os.environ,
            "CODEX_FOR_CLAUDE_REVIEW_GATE": "off",
            "CLAUDE_PLUGIN_DATA": str(tmp_path / "data"),
            "NODE_ENV": "test",
            "CODEX_FOR_CLAUDE_TEST_HOOK_THROW": "1",
        },
        input=json.dumps({"cwd": str(tmp_path)}),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_codex_state_writes_are_atomic(tmp_path):
    payload = run_node_script(
        """
        import { getConfig, setConfig } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        setConfig(cwd, 'stopReviewGate', true);
        console.log(JSON.stringify(getConfig(cwd)));
        """,
        env={"CLAUDE_PLUGIN_DATA": str(tmp_path / "data")},
        args=[str(tmp_path)],
    )
    assert payload["stopReviewGate"] is True
    state_source = read_text(PLUGIN / "scripts" / "lib" / "state.mjs")
    assert "function saveState" in state_source
    assert "function withStateLock" in state_source
    assert "withStateLock(cwd" in state_source
    assert "writeAtomicJson" in state_source
    assert "fs.renameSync" in state_source


def test_codex_stop_gate_result_fail_open_for_non_findings():
    payload = run_node_script(
        """
        import { classifyStopGateResult } from './plugins/codex/scripts/lib/stop-gate-result.mjs';
        const cases = ['timeout', 'auth', 'capacity', 'invalid-output'].map((kind) =>
          classifyStopGateResult({ ok: false, kind, reason: kind })
        );
        const open = classifyStopGateResult({ ok: false, kind: 'timeout', reason: 'timeout' }, { failOpen: true });
        const block = classifyStopGateResult({ ok: true, verdict: 'BLOCK', reason: 'bug' });
        const allow = classifyStopGateResult({ ok: true, verdict: 'ALLOW', reason: 'ok' });
        const legacyAllow = classifyStopGateResult({ ok: true, reason: null });
        console.log(JSON.stringify({ cases, open, block, allow, legacyAllow }));
        """
    )
    assert all(item["decision"] == "block" and item["toolFailure"] for item in payload["cases"])
    assert payload["open"]["decision"] == "allow"
    assert payload["open"]["toolFailure"] is True
    assert payload["open"]["reason"] == "timeout"
    assert payload["block"]["decision"] == "block"
    assert payload["block"]["toolFailure"] is False
    assert payload["block"]["reason"] == "bug"
    assert payload["allow"]["decision"] == "allow"
    assert payload["legacyAllow"]["decision"] == "allow"


def test_codex_stop_gate_results_have_single_classifier_consumer():
    hook_source = read_text(PLUGIN / "scripts" / "stop-review-gate-hook.mjs")
    main_body = js_function_body(hook_source, "main")
    parser_body = js_function_body(hook_source, "parseStopReviewOutput")
    classifier_body = js_function_body(hook_source, "classifyStopTaskProcessResult")
    run_body = js_function_body(hook_source, "runStopReview")
    assert "classifyStopGateResult(review" in main_body
    assert "review.ok" not in main_body
    assert "!review.ok" not in main_body
    assert "if (!review.ok) emit" not in hook_source
    parser_call = 'parseStopReviewOutput(payload?.rawOutput || "")'
    run_call = "runStopReview(cwd, input, stopGateLease, leaseEnv)"
    assert classifier_body.count(parser_call) == 1
    assert parser_call not in parser_body
    assert parser_call not in run_body
    assert 'acquireResourceLease("stop-gate"' not in run_body
    assert "stopGateLease.release" not in run_body
    assert parser_call not in main_body
    assert main_body.count(run_call) == 1


def test_codex_setup_exposes_review_gate_fail_open_flags(tmp_path):
    companion = read_text(PLUGIN / "scripts" / "codex-companion.mjs")
    setup_doc = read_text(PLUGIN / "commands" / "setup.md")
    assert "enable-review-gate-fail-open" in companion
    assert "disable-review-gate-fail-open" in companion
    assert "stopReviewGateFailOpen" in companion
    assert "--enable-review-gate-fail-open" in setup_doc
    assert "--disable-review-gate-fail-open" in setup_doc
    for block in fenced_bash_blocks(setup_doc):
        assert "$ARGUMENTS" not in block

    env = companion_env(tmp_path, fake_cli_dir(tmp_path, {"plugins": []}))
    enabled = run_companion(["setup", "--json", "--enable-review-gate-fail-open"], cwd=tmp_path, env=env)
    assert enabled.returncode == 0, enabled.stderr
    assert json.loads(enabled.stdout)["reviewGateFailOpen"] is True
    disabled = run_companion(["setup", "--json", "--disable-review-gate-fail-open"], cwd=tmp_path, env=env)
    assert disabled.returncode == 0, disabled.stderr
    assert json.loads(disabled.stdout)["reviewGateFailOpen"] is False
    rejected = run_companion(
        ["setup", "--enable-review-gate-fail-open", "--disable-review-gate-fail-open"],
        cwd=tmp_path,
        env=env,
    )
    assert rejected.returncode != 0
    assert "Choose either --enable-review-gate-fail-open or --disable-review-gate-fail-open" in rejected.stderr


def test_codex_preupgrade_stop_gate_state_defaults_fail_closed(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import { ensureStateDir, getConfig, resolveStateFile } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        ensureStateDir(cwd);
        fs.writeFileSync(resolveStateFile(cwd), JSON.stringify({ version: 1, config: { stopReviewGate: true }, jobs: [] }) + '\\n');
        console.log(JSON.stringify(getConfig(cwd)));
        """,
        env={"CLAUDE_PLUGIN_DATA": str(tmp_path / "data")},
        args=[str(tmp_path)],
    )
    assert payload["stopReviewGate"] is True
    assert payload["stopReviewGateFailOpen"] is False


def test_codex_stop_gate_parser_preserves_block_verdict():
    payload = run_node_script(
        """
        import { parseStopReviewOutput } from './plugins/codex/scripts/stop-review-gate-hook.mjs';
        const block = parseStopReviewOutput('BLOCK: real bug');
        const multi = parseStopReviewOutput('BLOCK: short\\nfull detail line');
        const longBlock = parseStopReviewOutput('BLOCK: ' + 'x'.repeat(10000));
        const allow = parseStopReviewOutput('\\nALLOW: ok');
        const invalid = parseStopReviewOutput('looks fine');
        console.log(JSON.stringify({ block, multi, longBlock, allow, invalid }));
        """
    )
    assert payload["block"]["ok"] is True
    assert payload["block"]["verdict"] == "BLOCK"
    assert payload["block"]["reason"] == "real bug"
    assert payload["multi"]["verdict"] == "BLOCK"
    assert payload["multi"]["reason"] == "short\nfull detail line"
    assert len(payload["longBlock"]["reason"]) <= 4000
    assert payload["longBlock"]["reason"].endswith("\n[truncated]")
    assert payload["allow"]["verdict"] == "ALLOW"
    assert payload["invalid"]["kind"] == "invalid-output"


def test_codex_stop_gate_parses_verdict_before_nonzero_status_failure():
    payload = run_node_script(
        """
        import { classifyStopTaskProcessResult } from './plugins/codex/scripts/stop-review-gate-hook.mjs';
        const allow = classifyStopTaskProcessResult({ status: 1, stdout: JSON.stringify({ rawOutput: 'ALLOW: ok' }), stderr: 'exit 1' });
        const allowWithError = classifyStopTaskProcessResult({ status: 0, error: new Error('spawn failed'), stdout: JSON.stringify({ rawOutput: 'ALLOW: ok' }), stderr: '' });
        const block = classifyStopTaskProcessResult({ status: 1, stdout: JSON.stringify({ rawOutput: 'BLOCK: bug' }), stderr: 'exit 1' });
        console.log(JSON.stringify({ allow, allowWithError, block }));
        """
    )
    assert payload["allow"]["ok"] is False
    assert payload["allow"]["kind"] == "status"
    assert payload["allow"]["reason"] == "exit 1"
    assert payload["allowWithError"]["ok"] is False
    assert payload["allowWithError"]["kind"] == "status"
    assert payload["allowWithError"]["reason"] == "spawn failed"
    assert payload["block"]["ok"] is True
    assert payload["block"]["verdict"] == "BLOCK"
    assert payload["block"]["reason"] == "bug"


def test_codex_stop_gate_block_verdict_wins_over_nonzero_status_behavior():
    payload = run_node_script(
        """
        import { classifyStopGateResult } from './plugins/codex/scripts/lib/stop-gate-result.mjs';
        import { classifyStopTaskProcessResult } from './plugins/codex/scripts/stop-review-gate-hook.mjs';
        const review = classifyStopTaskProcessResult({ status: 75, stdout: JSON.stringify({ rawOutput: 'BLOCK: capacity masked finding' }), stderr: 'capacity' });
        console.log(JSON.stringify(classifyStopGateResult(review, { failOpen: true })));
        """
    )
    assert payload["decision"] == "block"
    assert payload["toolFailure"] is False
    assert payload["reason"] == "capacity masked finding"


def test_codex_stop_gate_allow_nonzero_is_tool_failure_even_with_fail_open():
    payload = run_node_script(
        """
        import { classifyStopGateResult } from './plugins/codex/scripts/lib/stop-gate-result.mjs';
        import { classifyStopTaskProcessResult } from './plugins/codex/scripts/stop-review-gate-hook.mjs';
        const review = classifyStopTaskProcessResult({ status: 1, stdout: JSON.stringify({ rawOutput: 'ALLOW: ok' }), stderr: 'wrapper failed' });
        console.log(JSON.stringify({
          closed: classifyStopGateResult(review),
          open: classifyStopGateResult(review, { failOpen: true })
        }));
        """
    )
    assert payload["closed"]["decision"] == "block"
    assert payload["closed"]["toolFailure"] is True
    assert payload["closed"]["reason"] == "wrapper failed"
    assert payload["open"]["decision"] == "allow"
    assert payload["open"]["toolFailure"] is True


def test_codex_stop_gate_full_hook_blocks_block_verdict(tmp_path):
    bin_dir = fake_codex_app_server_dir(tmp_path)
    env = {
        **os.environ,
        **governor_env(tmp_path),
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "CODEX_TEST_STOP_OUTPUT": "BLOCK: found a real issue",
    }
    setup = run_node_script(
        """
        import { setConfig } from './plugins/codex/scripts/lib/state.mjs';
        setConfig(process.argv[1], 'stopReviewGate', true);
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )
    assert setup["ok"] is True
    result = subprocess.run(
        [NODE, str(PLUGIN / "scripts" / "stop-review-gate-hook.mjs")],
        cwd=tmp_path,
        env=env,
        input=json.dumps({"cwd": str(tmp_path), "last_assistant_message": "done"}),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"decision": "block", "reason": "found a real issue"}


def test_codex_stop_gate_full_hook_blocks_unavailable_codex_by_default(tmp_path):
    env = {**os.environ, "CLAUDE_PLUGIN_DATA": str(tmp_path / "data"), "PATH": ""}
    run_node_script(
        """
        import { setConfig } from './plugins/codex/scripts/lib/state.mjs';
        setConfig(process.argv[1], 'stopReviewGate', true);
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )
    result = subprocess.run(
        [NODE, str(PLUGIN / "scripts" / "stop-review-gate-hook.mjs")],
        cwd=tmp_path,
        env=env,
        input=json.dumps({"cwd": str(tmp_path)}),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "Codex is not set up for the review gate" in payload["reason"]
    assert result.stderr == ""


def test_codex_stop_gate_full_hook_allows_unavailable_codex_only_with_fail_open(tmp_path):
    env = {**os.environ, "CLAUDE_PLUGIN_DATA": str(tmp_path / "data"), "PATH": ""}
    run_node_script(
        """
        import { setConfig } from './plugins/codex/scripts/lib/state.mjs';
        setConfig(process.argv[1], 'stopReviewGate', true);
        setConfig(process.argv[1], 'stopReviewGateFailOpen', true);
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )
    result = subprocess.run(
        [NODE, str(PLUGIN / "scripts" / "stop-review-gate-hook.mjs")],
        cwd=tmp_path,
        env=env,
        input=json.dumps({"cwd": str(tmp_path)}),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert "[codex review-gate] Codex is not set up for the review gate" in result.stderr


def test_codex_stop_gate_non_json_block_output_is_tool_failure():
    payload = run_node_script(
        """
        import { classifyStopTaskProcessResult } from './plugins/codex/scripts/stop-review-gate-hook.mjs';
        const result = classifyStopTaskProcessResult({ status: 0, stdout: 'BLOCK: untrusted bare output', stderr: '' });
        console.log(JSON.stringify(result));
        """
    )
    assert payload["ok"] is False
    assert payload["kind"] == "invalid-json"


def test_codex_stop_gate_disabled_hook_exception_does_not_block(tmp_path):
    result = subprocess.run(
        [NODE, str(PLUGIN / "scripts" / "stop-review-gate-hook.mjs")],
        cwd=tmp_path,
        env={
            **os.environ,
            "CODEX_FOR_CLAUDE_REVIEW_GATE": "off",
            "NODE_ENV": "test",
            "CODEX_FOR_CLAUDE_TEST_HOOK_THROW": "1",
            "CLAUDE_PLUGIN_DATA": str(tmp_path / "data"),
        },
        input=json.dumps({"cwd": str(tmp_path)}),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_codex_stop_gate_enabled_hook_exception_blocks_by_default(tmp_path):
    env = {**os.environ, "CLAUDE_PLUGIN_DATA": str(tmp_path / "data")}
    run_node_script(
        """
        import { setConfig } from './plugins/codex/scripts/lib/state.mjs';
        setConfig(process.argv[1], 'stopReviewGate', true);
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )
    result = subprocess.run(
        [NODE, str(PLUGIN / "scripts" / "stop-review-gate-hook.mjs")],
        cwd=tmp_path,
        env={**env, "NODE_ENV": "test", "CODEX_FOR_CLAUDE_TEST_HOOK_THROW": "1"},
        input=json.dumps({"cwd": str(tmp_path)}),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "test hook crash" in payload["reason"]


def test_codex_stop_gate_internal_timeout_is_below_host_timeout():
    hook_source = read_text(PLUGIN / "scripts" / "stop-review-gate-hook.mjs")
    hooks = read_json(PLUGIN / "hooks" / "hooks.json")
    stop_timeout = hooks["hooks"]["Stop"][0]["hooks"][0]["timeout"]
    assert stop_timeout == 900
    assert "15 minutes" not in hook_source
    assert "15 * 60 * 1000" not in hook_source
    assert "const STOP_REVIEW_TIMEOUT_MS = 8 * 60 * 1000" in hook_source
    assert "const STOP_GATE_MUTEX_WAIT_MAX_MS = 60 * 1000" in hook_source
    assert (8 * 60) + 60 < stop_timeout - 240


def test_codex_stop_gate_mutex_wait_env_is_clamped():
    payload = run_node_script(
        """
        import { stopGateLeaseEnv } from './plugins/codex/scripts/stop-review-gate-hook.mjs';
        const env = stopGateLeaseEnv({
          PATH: 'keep-path',
          HOME: 'keep-home',
          CLAUDE_PLUGIN_DATA: '/tmp/plugin-data',
          CODEX_FOR_CLAUDE_RESOURCE_LOCK_DIR: '/tmp/locks',
          CODEX_FOR_CLAUDE_MUTEX_WAIT_MS: '999999'
        });
        console.log(JSON.stringify(env));
        """
    )
    assert payload["PATH"] == "keep-path"
    assert payload["HOME"] == "keep-home"
    assert payload["CLAUDE_PLUGIN_DATA"] == "/tmp/plugin-data"
    assert payload["CODEX_FOR_CLAUDE_RESOURCE_LOCK_DIR"] == "/tmp/locks"
    assert payload["CODEX_FOR_CLAUDE_MUTEX_WAIT_MS"] == "60000"


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
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          resolveJobFile,
          resolveJobLogFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const jobFile = resolveJobFile(cwd, 'cancel-tombstoned-sidecar-only');
        const logFile = resolveJobLogFile(cwd, 'cancel-tombstoned-sidecar-only');
        console.log(JSON.stringify({
          jobFileExists: fs.existsSync(jobFile),
          jobFileText: fs.existsSync(jobFile) ? fs.readFileSync(jobFile, 'utf8') : '',
          logFileExists: fs.existsSync(logFile),
          logFileText: fs.existsSync(logFile) ? fs.readFileSync(logFile, 'utf8') : ''
        }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    assert result.returncode != 0
    assert 'No job found for "cancel-tombstoned-sidecar-only"' in result.stderr
    assert payload["jobFileExists"] is False
    assert "cancel tombstoned secret" not in payload["jobFileText"]
    assert payload["logFileExists"] is False
    assert "cancel tombstoned log" not in payload["logFileText"]


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


def test_codex_cancel_rejects_when_sidecar_disappears_after_resolution(tmp_path):
    env = governor_env(tmp_path)
    script = """
        import fs from 'node:fs';

        const cwd = process.argv[1];
        const state = await import('./plugins/codex/scripts/lib/state.mjs');
        const companion = await import('./plugins/codex/scripts/codex-companion.mjs');
        const job = {
          id: 'cancel-sidecar-disappears',
          status: 'running',
          kind: 'task',
          kindLabel: 'rescue',
          jobClass: 'task',
          title: 'Cancel sidecar disappears',
          workspaceRoot: cwd,
          sessionId: 'session-cancel-sidecar-disappears',
          pid: 99999999,
          logFile: state.resolveJobLogFile(cwd, 'cancel-sidecar-disappears'),
          request: { secret: 'cancel sidecar disappears secret' },
          updatedAt: new Date().toISOString()
        };
        state.upsertJob(cwd, job);
        state.writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, 'cancel sidecar disappears log\\n', 'utf8');

        const originalExistsSync = fs.existsSync;
        let injected = false;
        fs.existsSync = function patchedExistsSync(filePath) {
          const result = originalExistsSync.call(this, filePath);
          if (!injected && result && String(filePath).endsWith('/cancel-sidecar-disappears.json')) {
            injected = true;
            state.updateState(cwd, (current) => {
              state.markSessionEnded(current, 'session-cancel-sidecar-disappears');
              current.jobs = current.jobs.filter((item) => item.id !== job.id);
            });
            fs.rmSync(filePath, { force: true });
            fs.rmSync(job.logFile, { force: true });
          }
          return result;
        };

        let errorMessage = '';
        try {
          await companion.__testHooks.handleCancel(['cancel-sidecar-disappears', '--cwd', cwd, '--json']);
        } catch (error) {
          errorMessage = error instanceof Error ? error.message : String(error);
        } finally {
          fs.existsSync = originalExistsSync;
        }
        const jobFile = state.resolveJobFile(cwd, job.id);
        console.log(JSON.stringify({
          injected,
          errorMessage,
          jobs: state.listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(job.logFile)
        }));
    """
    payload = run_node_script(script, env=env, args=[str(tmp_path)])

    assert payload["injected"] is True
    assert "ended before job cancel-sidecar-disappears could be cancelled" in payload["errorMessage"]
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
    hook_source = read_text(PLUGIN / "scripts" / "stop-review-gate-hook.mjs")
    companion_source = read_text(PLUGIN / "scripts" / "codex-companion.mjs")
    heartbeat = js_function_body(source, "writeHeartbeatIfRunning")
    progress = js_function_body(source, "createJobProgressUpdater")
    run_tracked = js_function_body(source, "runTrackedJob")
    task_body = js_function_body(companion_source, "handleTask")
    assert 'process.env.CODEX_FOR_CLAUDE_DISABLE_HEARTBEAT === "1"' in heartbeat
    assert 'process.env.CODEX_FOR_CLAUDE_DISABLE_PROGRESS_UPDATES === "1"' in progress
    assert 'CODEX_FOR_CLAUDE_DISABLE_HEARTBEAT: "1"' in hook_source
    assert 'CODEX_FOR_CLAUDE_DISABLE_PROGRESS_UPDATES: "1"' in hook_source
    assert 'CODEX_FOR_CLAUDE_FILE_LOCK_WAIT_MS: "35000"' in hook_source
    assert 'CODEX_FOR_CLAUDE_SKIP_STATE_PRUNE: "1"' in hook_source
    assert "verifyStopGateChildTask()" in task_body
    assert "verifyResourceLease" in companion_source
    assert "expectedParentPid: process.ppid" in companion_source
    assert 'expectedCommand: "stop-review-gate"' in companion_source
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
    assert run_tracked.index("if (!completedJobFile)") < run_tracked.index("appendLogBlockIfJobCurrent(")
    assert "throw sessionEndedFinishError(runningRecord)" in run_tracked
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
        let executionStatus = null;
        let errorMessage = '';
        try {
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
          executionStatus = execution.exitStatus;
        } catch (error) {
          errorMessage = error instanceof Error ? error.message : String(error);
        }
        const jobFile = resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          executionStatus,
          errorMessage,
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          jobFileText: fs.existsSync(jobFile) ? fs.readFileSync(jobFile, 'utf8') : '',
          logFileExists: fs.existsSync(job.logFile)
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["executionStatus"] is None
    assert "ended before job terminal-ended-session could finish" in payload["errorMessage"]
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
        let executionStatus = null;
        let errorMessage = '';
        try {
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
          executionStatus = execution.exitStatus;
        } catch (error) {
          errorMessage = error instanceof Error ? error.message : String(error);
        }
        const jobFile = state.resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          executionStatus,
          errorMessage,
          jobs: state.listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(job.logFile),
          logFileText: fs.existsSync(job.logFile) ? fs.readFileSync(job.logFile, 'utf8') : ''
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["executionStatus"] is None
    assert "ended before job terminal-log-race could finish" in payload["errorMessage"]
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
        let executionStatus = null;
        let errorMessage = '';
        try {
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
          executionStatus = execution.exitStatus;
        } catch (error) {
          errorMessage = error instanceof Error ? error.message : String(error);
        }
        const jobFile = state.resolveJobFile(cwd, job.id);

        console.log(JSON.stringify({
          executionStatus,
          errorMessage,
          injected,
          jobs: state.listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(job.logFile),
          logFileText: fs.existsSync(job.logFile) ? fs.readFileSync(job.logFile, 'utf8') : ''
        }));
        """,
        args=[str(tmp_path)],
    )

    assert payload["executionStatus"] is None
    assert "ended before job terminal-final-output-race could finish" in payload["errorMessage"]
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
    assert cancel.count("hasEndedSession(workspaceRoot, job.sessionId)") >= 2
    assert cancel.index("const interrupt = await interruptAppServerTurn") < cancel.index(
        "hasEndedSession(workspaceRoot, job.sessionId)",
        cancel.index("const interrupt = await interruptAppServerTurn"),
    )
    assert cancel.index(
        "hasEndedSession(workspaceRoot, job.sessionId)",
        cancel.index("const interrupt = await interruptAppServerTurn"),
    ) < cancel.index("terminateProcessTree(job.pid")
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
    setup_payload = run_node_script(
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
        console.log(JSON.stringify({
          jobFile: resolveJobFile(cwd, job.id),
          logFile: job.logFile
        }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    result = run_companion(["status", "--cwd", str(tmp_path), "--json", "--all"], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    status_payload = json.loads(result.stdout)
    text = json.dumps(status_payload)
    assert all(job["id"] != "status-tombstoned-sidecar-only" for job in status_payload["running"])
    assert "PRIVATE_TOMBSTONED_REQUEST" not in text
    assert "PRIVATE_TOMBSTONED_LOG" not in text
    assert not pathlib.Path(setup_payload["jobFile"]).exists()
    assert not pathlib.Path(setup_payload["logFile"]).exists()


def test_codex_status_cleans_tombstoned_sidecar_with_legacy_shared_row(tmp_path):
    env = companion_env(tmp_path, fake_cli_dir(tmp_path, {"plugins": []}))
    setup_payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          markSessionEnded,
          resolveJobFile,
          resolveJobLogFile,
          updateState,
          upsertJob,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const jobId = 'status-tombstoned-sidecar-legacy-shared';
        const logFile = resolveJobLogFile(cwd, jobId);
        upsertJob(cwd, {
          id: jobId,
          status: 'running',
          phase: 'running',
          kind: 'task',
          title: 'PRIVATE_LEGACY_SHARED_TITLE',
          summary: 'PRIVATE_LEGACY_SHARED_SUMMARY',
          workspaceRoot: cwd,
          logFile,
          updatedAt: new Date().toISOString()
        });
        const sidecar = {
          id: jobId,
          status: 'running',
          phase: 'running',
          kind: 'task',
          title: 'PRIVATE_LEGACY_SIDECAR_TITLE',
          workspaceRoot: cwd,
          sessionId: 'session-status-legacy-shared-tombstone',
          request: { secret: 'PRIVATE_LEGACY_REQUEST' },
          logFile,
          updatedAt: new Date().toISOString()
        };
        writeJobFile(cwd, jobId, sidecar);
        fs.writeFileSync(logFile, '[2000-01-01T00:00:00.000Z] PRIVATE_LEGACY_LOG\\n', 'utf8');
        updateState(cwd, (state) => {
          markSessionEnded(state, 'session-status-legacy-shared-tombstone');
        }, { pruneJobFiles: false });
        console.log(JSON.stringify({
          jobFile: resolveJobFile(cwd, jobId),
          logFile
        }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    for _ in range(2):
        result = run_companion(["status", "--cwd", str(tmp_path), "--json", "--all"], cwd=tmp_path, env=env)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        text = json.dumps(payload)
        assert all(job["id"] != "status-tombstoned-sidecar-legacy-shared" for job in payload["running"])
        assert all(job["id"] != "status-tombstoned-sidecar-legacy-shared" for job in payload["recent"])
        if payload["latestFinished"]:
            assert payload["latestFinished"]["id"] != "status-tombstoned-sidecar-legacy-shared"
        assert "PRIVATE_LEGACY_SHARED_TITLE" not in text
        assert "PRIVATE_LEGACY_SHARED_SUMMARY" not in text
        assert "PRIVATE_LEGACY_SIDECAR_TITLE" not in text
        assert "PRIVATE_LEGACY_REQUEST" not in text
        assert "PRIVATE_LEGACY_LOG" not in text

    verify_payload = run_node_script(
        """
        import fs from 'node:fs';
        import { listJobs } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        const jobFile = process.argv[2];
        const logFile = process.argv[3];
        console.log(JSON.stringify({
          jobs: listJobs(cwd),
          jobFileExists: fs.existsSync(jobFile),
          logFileExists: fs.existsSync(logFile)
        }));
        """,
        env=env,
        args=[str(tmp_path), setup_payload["jobFile"], setup_payload["logFile"]],
    )
    assert verify_payload["jobs"] == []
    assert verify_payload["jobFileExists"] is False
    assert verify_payload["logFileExists"] is False


def test_codex_status_cleans_tombstoned_shared_only_job_and_log(tmp_path):
    env = companion_env(tmp_path, fake_cli_dir(tmp_path, {"plugins": []}))
    setup_payload = run_node_script(
        """
        import fs from 'node:fs';
        import path from 'node:path';
        import {
          resolveJobLogFile,
          resolveStateFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'status-tombstoned-shared-only',
          status: 'running',
          phase: 'running',
          kind: 'task',
          title: 'PRIVATE_SHARED_ONLY_TITLE',
          summary: 'PRIVATE_SHARED_ONLY_SUMMARY',
          workspaceRoot: cwd,
          sessionId: 'session-status-shared-only',
          logFile: resolveJobLogFile(cwd, 'status-tombstoned-shared-only'),
          updatedAt: new Date().toISOString()
        };
        fs.writeFileSync(job.logFile, '[2000-01-01T00:00:00.000Z] PRIVATE_SHARED_ONLY_LOG\\n', 'utf8');
        const stateFile = resolveStateFile(cwd);
        fs.mkdirSync(path.dirname(stateFile), { recursive: true });
        fs.writeFileSync(stateFile, `${JSON.stringify({
          version: 1,
          config: { stopReviewGate: false },
          endedSessions: ['session-status-shared-only'],
          jobs: [job]
        }, null, 2)}\\n`, 'utf8');
        console.log(JSON.stringify({ stateFile, logFile: job.logFile }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    result = run_companion(["status", "--cwd", str(tmp_path), "--json", "--all"], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    status_payload = json.loads(result.stdout)
    text = json.dumps(status_payload)
    assert all(job["id"] != "status-tombstoned-shared-only" for job in status_payload["running"])
    assert status_payload["latestFinished"] is None
    assert all(job["id"] != "status-tombstoned-shared-only" for job in status_payload["recent"])
    assert "PRIVATE_SHARED_ONLY_TITLE" not in text
    assert "PRIVATE_SHARED_ONLY_SUMMARY" not in text
    assert "PRIVATE_SHARED_ONLY_LOG" not in text
    verify_payload = run_node_script(
        """
        import fs from 'node:fs';
        import { listJobs } from './plugins/codex/scripts/lib/state.mjs';
        const cwd = process.argv[1];
        const logFile = process.argv[2];
        console.log(JSON.stringify({
          jobs: listJobs(cwd),
          logFileExists: fs.existsSync(logFile)
        }));
        """,
        env=env,
        args=[str(tmp_path), setup_payload["logFile"]],
    )
    assert verify_payload["jobs"] == []
    assert verify_payload["logFileExists"] is False


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


def test_codex_status_removes_stale_shared_row_when_sidecar_is_freshly_tombstoned(tmp_path):
    payload = run_node_script(
        """
        import fs from 'node:fs';
        import {
          markSessionEnded,
          resolveJobLogFile,
          resolveJobsDir,
          updateState,
          upsertJob,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const job = {
          id: 'status-stale-shared-sidecar-race',
          status: 'running',
          phase: 'running',
          kind: 'task',
          title: 'PRIVATE_STALE_SHARED_TITLE',
          summary: 'PRIVATE_STALE_SHARED_SUMMARY',
          workspaceRoot: cwd,
          sessionId: 'session-status-stale-shared-race',
          request: { secret: 'PRIVATE_STALE_SHARED_REQUEST' },
          logFile: resolveJobLogFile(cwd, 'status-stale-shared-sidecar-race'),
          updatedAt: new Date().toISOString()
        };
        upsertJob(cwd, job);
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, '[2000-01-01T00:00:00.000Z] PRIVATE_STALE_SHARED_LOG\\n', 'utf8');

        const jobsDir = resolveJobsDir(cwd);
        const originalReaddirSync = fs.readdirSync;
        let injected = false;
        fs.readdirSync = function patchedReaddirSync(dirPath, ...args) {
          if (!injected && String(dirPath) === jobsDir) {
            injected = true;
            updateState(cwd, (state) => {
              markSessionEnded(state, 'session-status-stale-shared-race');
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
    assert all(job["id"] != "status-stale-shared-sidecar-race" for job in payload["snapshot"]["running"])
    assert "PRIVATE_STALE_SHARED_TITLE" not in text
    assert "PRIVATE_STALE_SHARED_SUMMARY" not in text
    assert "PRIVATE_STALE_SHARED_REQUEST" not in text
    assert "PRIVATE_STALE_SHARED_LOG" not in text


def test_codex_status_rechecks_tombstone_after_progress_log_read(tmp_path):
    payload = run_node_script(
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
          id: 'status-progress-read-race',
          status: 'running',
          phase: 'running',
          kind: 'task',
          title: 'Status progress read race',
          workspaceRoot: cwd,
          sessionId: 'session-status-progress-read-race',
          logFile: resolveJobLogFile(cwd, 'status-progress-read-race'),
          updatedAt: new Date().toISOString()
        };
        upsertJob(cwd, job);
        writeJobFile(cwd, job.id, job);
        fs.writeFileSync(job.logFile, '[2000-01-01T00:00:00.000Z] PRIVATE_PROGRESS_READ_RACE\\n', 'utf8');

        const originalReadFileSync = fs.readFileSync;
        let injected = false;
        fs.readFileSync = function patchedReadFileSync(filePath, ...args) {
          const result = originalReadFileSync.call(this, filePath, ...args);
          if (!injected && String(filePath) === job.logFile) {
            injected = true;
            updateState(cwd, (state) => {
              markSessionEnded(state, 'session-status-progress-read-race');
              state.jobs = state.jobs.filter((item) => item.id !== job.id);
            });
          }
          return result;
        };

        const { buildStatusSnapshot } = await import('./plugins/codex/scripts/lib/job-control.mjs');
        const snapshot = buildStatusSnapshot(cwd, { all: true });
        fs.readFileSync = originalReadFileSync;
        console.log(JSON.stringify({ injected, snapshot }));
        """,
        args=[str(tmp_path)],
    )

    text = json.dumps(payload["snapshot"])
    assert payload["injected"] is True
    assert "PRIVATE_PROGRESS_READ_RACE" not in text
    assert all(job["id"] != "status-progress-read-race" for job in payload["snapshot"]["running"])


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


def test_codex_status_liveness_keeps_terminal_shared_status_with_stale_sidecar(tmp_path):
    env = companion_env(tmp_path, fake_cli_dir(tmp_path, {"plugins": []}))
    run_node_script(
        """
        import {
          upsertJob,
          writeJobFile
        } from './plugins/codex/scripts/lib/state.mjs';

        const cwd = process.argv[1];
        const shared = {
          id: 'terminal-shared-stale-sidecar',
          status: 'completed',
          phase: 'done',
          summary: 'completed in shared state',
          workspaceRoot: cwd,
          sessionId: 'session-terminal-shared-stale-sidecar',
          updatedAt: new Date().toISOString(),
          completedAt: new Date().toISOString(),
          pid: null
        };
        upsertJob(cwd, shared);
        writeJobFile(cwd, shared.id, {
          ...shared,
          status: 'running',
          phase: 'running',
          heartbeatAtMs: Date.now(),
          heartbeatAt: new Date().toISOString(),
          pid: process.pid
        });
        console.log(JSON.stringify({ ok: true }));
        """,
        env=env,
        args=[str(tmp_path)],
    )

    result = run_companion(["status", "--cwd", str(tmp_path), "--json", "--all"], cwd=tmp_path, env=env)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert all(job["id"] != "terminal-shared-stale-sidecar" for job in payload["running"])
    assert payload["latestFinished"]["id"] == "terminal-shared-stale-sidecar"
    assert payload["latestFinished"]["status"] == "completed"
    assert payload["latestFinished"]["liveness"]["state"] == "terminal"
    assert payload["latestFinished"]["liveness"]["reason"] == "completed"


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
    assert "isTerminalStatus(job.status)" in latest_body
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


def test_codex_github_actions_template_is_fork_safe(tmp_path):
    result = run_node(PLUGIN / "scripts" / "codex-companion.mjs", ["github-actions", "render", "--ref", "v0.2.0"], timeout=10)
    assert result.returncode == 0, result.stderr
    text = result.stdout
    assert "pull_request:" in text
    assert "pull_request_target" not in text
    assert "contents: read" in text
    assert "claude plugin marketplace add \"$marketplace_dir\" --scope user" in text
    assert "claude plugin install codex@external-models-for-claude --scope user" in text
    assert "claude plugin list --json" in text
    assert "installPath" in text
    assert "plugin.path" in text
    assert "plugin.root" in text
    assert "HEAD_REPO: ${{ github.event.pull_request.head.repo.full_name }}" in text
    assert "BASE_REPO: ${{ github.repository }}" in text
    assert "steps.fork-safety.outputs.safe_to_review == 'true'" in text
    assert "Codex review skipped because pull request head repository is not this repository" in text
    assert '{"status":"skipped","reason":"external-head-repository"}' in text
    if "REPLACE_WITH_RELEASE_HOST_CODEX_CLI_VERSION" in text or "REPLACE_WITH_RELEASE_HOST_CLAUDE_CODE_VERSION" in text:
        assert "Codex auth steps omitted until release-host CLI/auth contract is verified." in text
        assert "Codex review execution omitted until release-host CLI/auth contract is verified." in text
        assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" not in text
        assert "$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs\" review --json" not in text
    else:
        assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in text
        assert "codex login --with-api-key" in text
        assert "$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs" in text
        assert "codex-for-claude-review.stderr" in text
        assert '"status": "failed"' in text
    if "REPLACE_WITH_RELEASE_HOST_CODEX_CLI_VERSION" not in text:
        assert re.search(r'CODEX_CLI_NPM_VERSION: "[0-9]+\.[0-9]+\.[0-9]+"', text)
    if "REPLACE_WITH_RELEASE_HOST_CLAUDE_CODE_VERSION" not in text:
        assert re.search(r'CLAUDE_CODE_NPM_VERSION: "[0-9]+\.[0-9]+\.[0-9]+"', text)
    assert 'npm install -g "@openai/codex@$CODEX_CLI_NPM_VERSION"' in text
    assert 'npm install -g "@anthropic-ai/claude-code@$CLAUDE_CODE_NPM_VERSION"' in text
    assert "CODEX_API_KEY" not in text
    assert "--dangerously-skip-permissions" not in text
    assert_no_machine_paths(text)
    match = re.search(r"// codex-plugin-root-resolver-begin\n(?P<script>.*?)\n\s*// codex-plugin-root-resolver-end", text, re.S)
    assert match, "embedded plugin-root resolver script not found between sentinel markers"
    resolver = tmp_path / "resolver.cjs"
    resolver.write_text(match.group("script"), encoding="utf8")
    check = subprocess.run([NODE, "--check", str(resolver)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert check.returncode == 0, check.stderr
    samples = [
        [{"id": "codex@external-models-for-claude", "installPath": "/tmp/install-path"}],
        [{"name": "codex", "path": "/tmp/path-field"}],
        [{"id": "codex@external-models-for-claude", "root": "/tmp/root-field"}],
    ]
    for sample in samples:
        run = subprocess.run([NODE, str(resolver)], input=json.dumps(sample), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        assert run.returncode == 0, run.stderr
        assert run.stdout.startswith("/tmp/")


def test_codex_github_actions_root_resolver_matches_install_consistency_precedence(tmp_path):
    result = run_node(PLUGIN / "scripts" / "codex-companion.mjs", ["github-actions", "render", "--ref", "v0.2.0"], timeout=10)
    assert result.returncode == 0, result.stderr
    match = re.search(r"// codex-plugin-root-resolver-begin\n(?P<script>.*?)\n\s*// codex-plugin-root-resolver-end", result.stdout, re.S)
    assert match, "embedded plugin-root resolver script not found between sentinel markers"
    resolver = tmp_path / "resolver.cjs"
    resolver.write_text(match.group("script"), encoding="utf8")
    install_script = (
        "import fs from 'node:fs';"
        "const i = await import('./plugins/codex/scripts/lib/install-consistency.mjs');"
        "const entry = i.installedCodexEntry(JSON.parse(fs.readFileSync(0, 'utf8')));"
        "process.stdout.write(entry?.installPath || '');"
    )
    samples = [
        [{"id": "codex@external-models-for-claude", "installPath": "/tmp/install-path"}],
        [{"name": "codex", "path": "/tmp/path-field"}],
        [{"id": "codex@external-models-for-claude", "root": "/tmp/root-field"}],
        {"plugins": [{"name": "other", "installPath": "/tmp/other"}, {"name": "codex", "path": "/tmp/codex"}]},
    ]
    for sample in samples:
        raw = json.dumps(sample)
        embedded = subprocess.run([NODE, str(resolver)], input=raw, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        install = subprocess.run([NODE, "--input-type=module", "-e", install_script], input=raw, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        assert embedded.returncode == 0, embedded.stderr
        assert install.returncode == 0, install.stderr
        assert embedded.stdout == install.stdout


def test_codex_github_actions_root_resolver_rootless_entry_fails_ci(tmp_path):
    result = run_node(PLUGIN / "scripts" / "codex-companion.mjs", ["github-actions", "render", "--ref", "v0.2.0"], timeout=10)
    assert result.returncode == 0, result.stderr
    match = re.search(r"// codex-plugin-root-resolver-begin\n(?P<script>.*?)\n\s*// codex-plugin-root-resolver-end", result.stdout, re.S)
    assert match, "embedded plugin-root resolver script not found between sentinel markers"
    resolver = tmp_path / "resolver.cjs"
    resolver.write_text(match.group("script"), encoding="utf8")
    raw = json.dumps([{"id": "codex@external-models-for-claude", "name": "codex"}])
    embedded = subprocess.run([NODE, str(resolver)], input=raw, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert embedded.returncode == 1
    assert "Could not resolve" in embedded.stderr


def test_codex_github_actions_contract_constants_drive_rendered_workflow():
    script = (
        "const g = await import('./plugins/codex/scripts/lib/github-actions.mjs');"
        "const text = g.renderWorkflow({ref:'v0.2.0'});"
        "process.stdout.write(JSON.stringify({releaseHostVerified:g.RELEASE_HOST_CONTRACTS_VERIFIED, codexVersion:g.CODEX_CLI_NPM_VERSION, claudeVersion:g.CLAUDE_CODE_NPM_VERSION, codexVersionIncluded:text.includes(`CODEX_CLI_NPM_VERSION: \"${g.CODEX_CLI_NPM_VERSION}\"`), claudeVersionIncluded:text.includes(`CLAUDE_CODE_NPM_VERSION: \"${g.CLAUDE_CODE_NPM_VERSION}\"`), helpIncluded:text.includes(g.CODEX_CLI_AUTH_HELP_COMMAND), loginIncluded:text.includes(g.CODEX_CLI_AUTH_LOGIN_COMMAND), validation:g.validateWorkflow(text)}));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    if not payload["releaseHostVerified"]:
        pytest.skip("ready workflow assertions require RELEASE_HOST_CONTRACTS_VERIFIED=true from a saved release-host artifact")
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", payload["codexVersion"])
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", payload["claudeVersion"])
    assert payload["codexVersionIncluded"] is True
    assert payload["claudeVersionIncluded"] is True
    assert payload["helpIncluded"] is True
    assert payload["loginIncluded"] is True
    assert payload["validation"]["ok"] is True


def test_codex_github_actions_version_sentinels_are_replaced_together():
    script = (
        "const g = await import('./plugins/codex/scripts/lib/github-actions.mjs');"
        "process.stdout.write(JSON.stringify({paired:g.versionSentinelsPaired(), marker:g.RELEASE_HOST_CONTRACTS_VERIFIED, verified:g.releaseHostContractsVerified(), codex:g.CODEX_CLI_NPM_VERSION, claude:g.CLAUDE_CODE_NPM_VERSION, validation:g.validateWorkflow(g.renderWorkflow({ref:'v0.2.0'}))}));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["paired"] is True
    assert payload["verified"] is (
        payload["marker"] is True
        and not payload["codex"].startswith("REPLACE_WITH_")
        and not payload["claude"].startswith("REPLACE_WITH_")
    )
    paired_check = next(check for check in payload["validation"]["checks"] if check["name"] == "cli-version-sentinels-paired")
    assert paired_check["ok"] is True


def test_codex_github_actions_rejects_unresolved_cli_version_sentinel():
    script = (
        "const g = await import('./plugins/codex/scripts/lib/github-actions.mjs');"
        "process.stdout.write(JSON.stringify({version:g.CODEX_CLI_NPM_VERSION, validation:g.validateWorkflow(g.renderWorkflow({ref:'v0.2.0'}))}));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    if payload["version"] == "REPLACE_WITH_RELEASE_HOST_CODEX_CLI_VERSION":
        assert payload["validation"]["ok"] is False
        assert any(check["name"] == "codex-cli-version-pinned" and check["ok"] is False for check in payload["validation"]["checks"])


def test_codex_github_actions_ready_review_uses_pr_base_sha():
    source = read_text(PLUGIN / "scripts" / "lib" / "github-actions.mjs")
    assert 'review --base "$BASE_SHA" --json' in source
    assert 'review --json > codex-for-claude-review.json' not in source


def test_codex_github_actions_validator_rejects_extra_workflow_permissions():
    script = (
        "const g = await import('./plugins/codex/scripts/lib/github-actions.mjs');"
        "const text = g.renderWorkflow({ref:'v0.2.0'}).replace('permissions:\\n  contents: read', 'permissions:\\n  contents: read\\n  pull-requests: write');"
        "process.stdout.write(JSON.stringify(g.validateWorkflow(text)));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    permission_check = next(check for check in payload["checks"] if check["name"] == "minimal-contents-permission")
    assert permission_check["ok"] is False
    assert payload["structuralOk"] is False


def test_codex_github_actions_validator_rejects_extra_triggers_and_job_permissions():
    script = (
        "const g = await import('./plugins/codex/scripts/lib/github-actions.mjs');"
        "const base = g.renderWorkflow({ref:'v0.2.0'});"
        "const trigger = base.replace('on:\\n  pull_request:', 'on:\\n  pull_request:\\n  workflow_dispatch:');"
        "const jobPermissions = base.replace('    runs-on: ubuntu-latest', '    runs-on: ubuntu-latest\\n    permissions:\\n      pull-requests: write');"
        "const duplicateTrigger = `${base}\\non:\\n  workflow_dispatch:\\n`;"
        "const duplicatePermissions = `${base}\\npermissions:\\n  pull-requests: write\\n`;"
        "const inlineJobPermissions = base.replace('    runs-on: ubuntu-latest', '    runs-on: ubuntu-latest\\n    permissions: write-all');"
        "const quotedDuplicateTrigger = `${base}\\n\"on\":\\n  workflow_dispatch:\\n`;"
        "const quotedInlineJobPermissions = base.replace('    runs-on: ubuntu-latest', '    runs-on: ubuntu-latest\\n    \"permissions\": write-all');"
        "const spacedQuotedDuplicateTrigger = `${base}\\n\"on\" :\\n  workflow_dispatch:\\n`;"
        "const spacedQuotedInlineJobPermissions = base.replace('    runs-on: ubuntu-latest', '    runs-on: ubuntu-latest\\n    \"permissions\" : write-all');"
        "process.stdout.write(JSON.stringify({trigger:g.validateWorkflow(trigger), jobPermissions:g.validateWorkflow(jobPermissions), duplicateTrigger:g.validateWorkflow(duplicateTrigger), duplicatePermissions:g.validateWorkflow(duplicatePermissions), inlineJobPermissions:g.validateWorkflow(inlineJobPermissions), quotedDuplicateTrigger:g.validateWorkflow(quotedDuplicateTrigger), quotedInlineJobPermissions:g.validateWorkflow(quotedInlineJobPermissions), spacedQuotedDuplicateTrigger:g.validateWorkflow(spacedQuotedDuplicateTrigger), spacedQuotedInlineJobPermissions:g.validateWorkflow(spacedQuotedInlineJobPermissions)}));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    trigger_check = next(check for check in payload["trigger"]["checks"] if check["name"] == "has-pull-request-trigger")
    permission_check = next(check for check in payload["jobPermissions"]["checks"] if check["name"] == "minimal-contents-permission")
    duplicate_trigger_check = next(check for check in payload["duplicateTrigger"]["checks"] if check["name"] == "has-pull-request-trigger")
    duplicate_permission_check = next(check for check in payload["duplicatePermissions"]["checks"] if check["name"] == "minimal-contents-permission")
    inline_permission_check = next(check for check in payload["inlineJobPermissions"]["checks"] if check["name"] == "minimal-contents-permission")
    quoted_duplicate_trigger_check = next(check for check in payload["quotedDuplicateTrigger"]["checks"] if check["name"] == "has-pull-request-trigger")
    quoted_inline_permission_check = next(check for check in payload["quotedInlineJobPermissions"]["checks"] if check["name"] == "minimal-contents-permission")
    spaced_quoted_duplicate_trigger_check = next(check for check in payload["spacedQuotedDuplicateTrigger"]["checks"] if check["name"] == "has-pull-request-trigger")
    spaced_quoted_inline_permission_check = next(check for check in payload["spacedQuotedInlineJobPermissions"]["checks"] if check["name"] == "minimal-contents-permission")
    assert trigger_check["ok"] is False
    assert permission_check["ok"] is False
    assert duplicate_trigger_check["ok"] is False
    assert duplicate_permission_check["ok"] is False
    assert inline_permission_check["ok"] is False
    assert quoted_duplicate_trigger_check["ok"] is False
    assert quoted_inline_permission_check["ok"] is False
    assert spaced_quoted_duplicate_trigger_check["ok"] is False
    assert spaced_quoted_inline_permission_check["ok"] is False
    assert payload["trigger"]["structuralOk"] is False
    assert payload["jobPermissions"]["structuralOk"] is False
    assert payload["duplicateTrigger"]["structuralOk"] is False
    assert payload["duplicatePermissions"]["structuralOk"] is False
    assert payload["inlineJobPermissions"]["structuralOk"] is False
    assert payload["quotedDuplicateTrigger"]["structuralOk"] is False
    assert payload["quotedInlineJobPermissions"]["structuralOk"] is False
    assert payload["spacedQuotedDuplicateTrigger"]["structuralOk"] is False
    assert payload["spacedQuotedInlineJobPermissions"]["structuralOk"] is False


def test_codex_github_actions_validator_requires_tag_fetch_and_artifact_upload():
    script = (
        "const g = await import('./plugins/codex/scripts/lib/github-actions.mjs');"
        "const base = g.renderWorkflow({ref:'v0.2.0'});"
        "const mutableFetch = base.replace('refs/tags/$CODEX_FOR_CLAUDE_RELEASE_REF', 'main');"
        "const mutableCheckout = base.replace('git -C \"$marketplace_dir\" checkout FETCH_HEAD', 'git -C \"$marketplace_dir\" checkout FETCH_HEAD\\n          git -C \"$marketplace_dir\" checkout main');"
        "const mutableCheckoutVariable = base.replace('git -C \"$marketplace_dir\" checkout FETCH_HEAD', 'git -C \"$marketplace_dir\" checkout FETCH_HEAD\\n          git -C \"${marketplace_dir}\" checkout main');"
        "const extraMutableFetch = base.replace('git -C \"$marketplace_dir\" checkout FETCH_HEAD', 'git -C \"$marketplace_dir\" fetch --depth 1 origin main\\n          git -C \"$marketplace_dir\" checkout FETCH_HEAD');"
        "const extraApprovedStepShell = base.replace('claude plugin install codex@external-models-for-claude --scope user', 'claude plugin install codex@external-models-for-claude --scope user\\n          curl https://example.invalid/unexpected');"
        "const noArtifact = base.replace('      - uses: actions/upload-artifact@v4\\n        if: always()\\n        with:\\n          name: codex-for-claude-review\\n          path: codex-for-claude-review.*\\n          retention-days: 5\\n', '');"
        "const commentedArtifact = base.replace('      - uses: actions/upload-artifact@v4', '      # - uses: actions/upload-artifact@v4');"
        "const previewLine = `          printf '%s\\\\n' '{\"status\":\"preview\",\"reason\":\"release-host-cli-auth-contract-unverified\"}' > codex-for-claude-review.json`;"
        "const artifactBlock = '      - uses: actions/upload-artifact@v4\\n        if: always()\\n        with:\\n          name: codex-for-claude-review\\n          path: codex-for-claude-review.*\\n          retention-days: 5\\n';"
        "const artifactSpoof = base.replace(previewLine, `${previewLine}\\n          - uses: actions/upload-artifact@v4\\n            if: always()\\n            name: codex-for-claude-review\\n            path: codex-for-claude-review.*`).replace(artifactBlock, '');"
        "const scriptBodyStepsArtifactSpoof = base.replace(previewLine, `${previewLine}\\n          steps:\\n            - uses: actions/upload-artifact@v4\\n              if: always()\\n              with:\\n                name: codex-for-claude-review\\n                path: codex-for-claude-review.*`).replace(artifactBlock, '');"
        "process.stdout.write(JSON.stringify({mutableFetch:g.validateWorkflow(mutableFetch), mutableCheckout:g.validateWorkflow(mutableCheckout), mutableCheckoutVariable:g.validateWorkflow(mutableCheckoutVariable), extraMutableFetch:g.validateWorkflow(extraMutableFetch), extraApprovedStepShell:g.validateWorkflow(extraApprovedStepShell), noArtifact:g.validateWorkflow(noArtifact), commentedArtifact:g.validateWorkflow(commentedArtifact), artifactSpoof:g.validateWorkflow(artifactSpoof), scriptBodyStepsArtifactSpoof:g.validateWorkflow(scriptBodyStepsArtifactSpoof)}));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    install_check = next(check for check in payload["mutableFetch"]["checks"] if check["name"] == "marketplace-install")
    checkout_check = next(check for check in payload["mutableCheckout"]["checks"] if check["name"] == "marketplace-install")
    checkout_variable_check = next(check for check in payload["mutableCheckoutVariable"]["checks"] if check["name"] == "marketplace-install")
    extra_fetch_check = next(check for check in payload["extraMutableFetch"]["checks"] if check["name"] == "marketplace-install")
    extra_approved_step_shell_check = next(check for check in payload["extraApprovedStepShell"]["checks"] if check["name"] == "fork-safe-step-gates")
    artifact_check = next(check for check in payload["noArtifact"]["checks"] if check["name"] == "review-artifact-upload")
    commented_artifact_check = next(check for check in payload["commentedArtifact"]["checks"] if check["name"] == "review-artifact-upload")
    spoofed_artifact_check = next(check for check in payload["artifactSpoof"]["checks"] if check["name"] == "review-artifact-upload")
    script_body_steps_artifact_check = next(check for check in payload["scriptBodyStepsArtifactSpoof"]["checks"] if check["name"] == "review-artifact-upload")
    assert install_check["ok"] is False
    assert checkout_check["ok"] is False
    assert checkout_variable_check["ok"] is False
    assert extra_fetch_check["ok"] is False
    assert extra_approved_step_shell_check["ok"] is False
    assert artifact_check["ok"] is False
    assert commented_artifact_check["ok"] is False
    assert spoofed_artifact_check["ok"] is False
    assert script_body_steps_artifact_check["ok"] is False
    assert payload["mutableFetch"]["structuralOk"] is False
    assert payload["mutableCheckout"]["structuralOk"] is False
    assert payload["mutableCheckoutVariable"]["structuralOk"] is False
    assert payload["extraMutableFetch"]["structuralOk"] is False
    assert payload["extraApprovedStepShell"]["structuralOk"] is False
    assert payload["noArtifact"]["structuralOk"] is False
    assert payload["commentedArtifact"]["structuralOk"] is False
    assert payload["artifactSpoof"]["structuralOk"] is False
    assert payload["scriptBodyStepsArtifactSpoof"]["structuralOk"] is False


def test_codex_github_actions_validator_rejects_preview_auth_or_review_injection():
    script = (
        "const g = await import('./plugins/codex/scripts/lib/github-actions.mjs');"
        "const base = g.renderWorkflow({ref:'v0.2.0'});"
        "const auth = base.replace('      # Codex auth steps omitted until release-host CLI/auth contract is verified.', '      # Codex auth steps omitted until release-host CLI/auth contract is verified.\\n      OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}');"
        "const authAlt = base.replace('      # Codex auth steps omitted until release-host CLI/auth contract is verified.', '      # Codex auth steps omitted until release-host CLI/auth contract is verified.\\n      run: echo \"$TOKEN\" | codex login --with-api-key');"
        "const authWrapped = base.replace('      # Codex auth steps omitted until release-host CLI/auth contract is verified.', '      # Codex auth steps omitted until release-host CLI/auth contract is verified.\\n      run: printenv TOKEN | /usr/local/bin/codex login --with-api-\\\\\\nkey');"
        "const authAnsi = base.replace('      # Codex auth steps omitted until release-host CLI/auth contract is verified.', () => `      # Codex auth steps omitted until release-host CLI/auth contract is verified.\\n      run: co$'dex' login --with-api-$'key'`);"
        "const authAnsiEscaped = base.replace('      # Codex auth steps omitted until release-host CLI/auth contract is verified.', () => `      # Codex auth steps omitted until release-host CLI/auth contract is verified.\\n      run: co$'d\\\\x65x' login --with-api-$'k\\\\x65y'`);"
        "const review = base.replace('      - uses: actions/upload-artifact@v4', '      - name: Injected Codex review\\n        run: node \"$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs\" review --base \"$BASE_SHA\" --json\\n      - uses: actions/upload-artifact@v4');"
        "const reviewWrapped = base.replace('      - uses: actions/upload-artifact@v4', '      - name: Injected wrapped Codex review\\n        run: node \"$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs\" \\\\\\n          review --base \"$BASE_SHA\" --json\\n      - uses: actions/upload-artifact@v4');"
        "const reviewSplitPath = base.replace('      - uses: actions/upload-artifact@v4', '      - name: Injected split-path Codex review\\n        run: node \"$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.\\\\\\nmjs\" review --base \"$BASE_SHA\" --json\\n      - uses: actions/upload-artifact@v4');"
        "const reviewSplitAction = base.replace('      - uses: actions/upload-artifact@v4', '      - name: Injected split-action Codex review\\n        run: node \"$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs\" re\\\\\\nview --base \"$BASE_SHA\" --json\\n      - uses: actions/upload-artifact@v4');"
        "const reviewAnsi = base.replace('      - uses: actions/upload-artifact@v4', () => `      - name: Injected ansi Codex review\\n        run: node \"$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.$'mjs'\" re$'view' --base \"$BASE_SHA\" --json\\n      - uses: actions/upload-artifact@v4`);"
        "const reviewAnsiEscaped = base.replace('      - uses: actions/upload-artifact@v4', () => `      - name: Injected escaped ansi Codex review\\n        run: node \"$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.$'m\\\\x6as'\" re$'v\\\\x69ew' --base \"$BASE_SHA\" --json\\n      - uses: actions/upload-artifact@v4`);"
        "const reviewSubstitution = base.replace('      - uses: actions/upload-artifact@v4', '      - name: Injected substitution Codex review\\n        run: node \"$CLAUDE_PLUGIN_ROOT/scripts/$(printf codex-companion.mjs)\" $(printf review) --base \"$BASE_SHA\" --json\\n      - uses: actions/upload-artifact@v4');"
        "const reviewBacktickSubstitution = base.replace('      - uses: actions/upload-artifact@v4', '      - name: Injected backtick Codex review\\n        run: node \"$CLAUDE_PLUGIN_ROOT/scripts/`printf codex-companion.mjs`\" `printf review` --base \"$BASE_SHA\" --json\\n      - uses: actions/upload-artifact@v4');"
        "const reviewParameterExpansion = base.replace('      - uses: actions/upload-artifact@v4', '      - name: Injected parameter Codex review\\n        run: helper=codex-companion.mjs; action=review; node \"$CLAUDE_PLUGIN_ROOT/scripts/${helper}\" ${action} --base \"$BASE_SHA\" --json\\n      - uses: actions/upload-artifact@v4');"
        "process.stdout.write(JSON.stringify({auth:g.validateWorkflow(auth), authAlt:g.validateWorkflow(authAlt), authWrapped:g.validateWorkflow(authWrapped), authAnsi:g.validateWorkflow(authAnsi), authAnsiEscaped:g.validateWorkflow(authAnsiEscaped), review:g.validateWorkflow(review), reviewWrapped:g.validateWorkflow(reviewWrapped), reviewSplitPath:g.validateWorkflow(reviewSplitPath), reviewSplitAction:g.validateWorkflow(reviewSplitAction), reviewAnsi:g.validateWorkflow(reviewAnsi), reviewAnsiEscaped:g.validateWorkflow(reviewAnsiEscaped), reviewSubstitution:g.validateWorkflow(reviewSubstitution), reviewBacktickSubstitution:g.validateWorkflow(reviewBacktickSubstitution), reviewParameterExpansion:g.validateWorkflow(reviewParameterExpansion)}));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["auth"]["structuralOk"] is False
    assert payload["authAlt"]["structuralOk"] is False
    assert payload["authWrapped"]["structuralOk"] is False
    assert payload["authAnsi"]["structuralOk"] is False
    assert payload["authAnsiEscaped"]["structuralOk"] is False
    assert payload["review"]["structuralOk"] is False
    assert payload["reviewWrapped"]["structuralOk"] is False
    assert payload["reviewSplitPath"]["structuralOk"] is False
    assert payload["reviewSplitAction"]["structuralOk"] is False
    assert payload["reviewAnsi"]["structuralOk"] is False
    assert payload["reviewAnsiEscaped"]["structuralOk"] is False
    assert payload["reviewSubstitution"]["structuralOk"] is False
    assert payload["reviewBacktickSubstitution"]["structuralOk"] is False
    assert payload["reviewParameterExpansion"]["structuralOk"] is False
    auth_check = next(check for check in payload["auth"]["checks"] if check["name"] == "codex-auth-login")
    auth_alt_check = next(check for check in payload["authAlt"]["checks"] if check["name"] == "codex-auth-login")
    auth_wrapped_check = next(check for check in payload["authWrapped"]["checks"] if check["name"] == "codex-auth-login")
    auth_ansi_check = next(check for check in payload["authAnsi"]["checks"] if check["name"] == "codex-auth-login")
    auth_ansi_escaped_check = next(check for check in payload["authAnsiEscaped"]["checks"] if check["name"] == "codex-auth-login")
    review_check = next(check for check in payload["review"]["checks"] if check["name"] == "codex-review-step")
    review_wrapped_check = next(check for check in payload["reviewWrapped"]["checks"] if check["name"] == "codex-review-step")
    review_split_path_check = next(check for check in payload["reviewSplitPath"]["checks"] if check["name"] == "codex-review-step")
    review_split_action_check = next(check for check in payload["reviewSplitAction"]["checks"] if check["name"] == "codex-review-step")
    review_ansi_check = next(check for check in payload["reviewAnsi"]["checks"] if check["name"] == "codex-review-step")
    review_ansi_escaped_check = next(check for check in payload["reviewAnsiEscaped"]["checks"] if check["name"] == "codex-review-step")
    review_substitution_check = next(check for check in payload["reviewSubstitution"]["checks"] if check["name"] == "codex-review-step")
    review_backtick_substitution_check = next(check for check in payload["reviewBacktickSubstitution"]["checks"] if check["name"] == "codex-review-step")
    review_parameter_expansion_check = next(check for check in payload["reviewParameterExpansion"]["checks"] if check["name"] == "codex-review-step")
    assert auth_check["ok"] is False
    assert auth_alt_check["ok"] is False
    assert auth_wrapped_check["ok"] is False
    assert auth_ansi_check["ok"] is False
    assert auth_ansi_escaped_check["ok"] is False
    assert review_check["ok"] is False
    assert review_wrapped_check["ok"] is False
    assert review_split_path_check["ok"] is False
    assert review_split_action_check["ok"] is False
    assert review_ansi_check["ok"] is False
    assert review_ansi_escaped_check["ok"] is False
    assert review_substitution_check["ok"] is False
    assert review_backtick_substitution_check["ok"] is False
    assert review_parameter_expansion_check["ok"] is False


def test_codex_github_actions_validator_requires_step_scoped_fork_gates():
    script = (
        "const g = await import('./plugins/codex/scripts/lib/github-actions.mjs');"
        "const base = g.renderWorkflow({ref:'v0.2.0'});"
        "const reviewUngated = base.replace('      - name: Preview Codex review\\n        if: steps.fork-safety.outputs.safe_to_review == \\'true\\'', '      - name: Preview Codex review');"
        "const installUngated = base.replace('      - name: Install Codex for Claude plugin\\n        if: steps.fork-safety.outputs.safe_to_review == \\'true\\'', '      - name: Install Codex for Claude plugin');"
        "const extraUngated = base.replace('      - uses: actions/upload-artifact@v4', '      - name: Extra ungated shell\\n        shell: bash\\n        run: echo unsafe\\n      - uses: actions/upload-artifact@v4');"
        "const extraGated = base.replace('      - uses: actions/upload-artifact@v4', '      - name: Extra gated shell\\n        if: steps.fork-safety.outputs.safe_to_review == \\'true\\'\\n        shell: bash\\n        run: echo unexpected\\n      - uses: actions/upload-artifact@v4');"
        "const disguisedUngated = base.replace('      - uses: actions/upload-artifact@v4', '      - name: Extra disguised ungated shell\\n        shell: bash\\n        run: |\\n          if: steps.fork-safety.outputs.safe_to_review == \\'true\\'\\n          echo unsafe\\n      - uses: actions/upload-artifact@v4');"
        "const extraJob = base.replace('          retention-days: 5\\n', '          retention-days: 5\\n  unsafe-extra-job:\\n    runs-on: ubuntu-latest\\n    steps:\\n      - run: echo unsafe\\n');"
        "const quotedExtraJob = `${base}\\n\"jobs\" :\\n  unsafe-extra-job:\\n    uses: attacker/repo/.github/workflows/pwn.yml@main\\n`;"
        "const shorthandUngated = base.replace('      - uses: actions/upload-artifact@v4', '      - run: echo unsafe\\n      - uses: actions/upload-artifact@v4');"
        "const unsafeDetector = base.replace(/      - name: Detect fork safety[\\s\\S]*?      - uses: actions\\/setup-node@v4/, '      - name: Detect fork safety\\n        id: fork-safety\\n        shell: bash\\n        run: |\\n          echo \"safe_to_review=true\" >> \"$GITHUB_OUTPUT\"\\n          # Codex review skipped because pull request head repository is not this repository.\\n          # {\"status\":\"skipped\",\"reason\":\"external-head-repository\"}\\n      - uses: actions/setup-node@v4');"
        "const unsafeDetectorAfterFi = base.replace('          echo \"safe_to_review=true\" >> \"$GITHUB_OUTPUT\"\\n          fi', '          echo \"safe_to_review=true\" >> \"$GITHUB_OUTPUT\"\\n          fi\\n          echo \"safe_to_review=true\" >> \"$GITHUB_OUTPUT\"');"
        "const duplicateDetector = base.replace('      - uses: actions/setup-node@v4', '      - name: Detect fork safety\\n        shell: bash\\n        run: echo unsafe-from-fork\\n      - uses: actions/setup-node@v4');"
        "const detectorBlock = base.match(/      - name: Detect fork safety[\\s\\S]*?      - uses: actions\\/setup-node@v4/)[0].replace('      - uses: actions/setup-node@v4', '');"
        "const duplicateExactDetector = base.replace('      - uses: actions/setup-node@v4', `${detectorBlock}      - uses: actions/setup-node@v4`);"
        "const scriptBodyStepsDetector = base.replace(detectorBlock, '').replace('          printf \\'%s\\\\n\\' \\'{\"status\":\"preview\",\"reason\":\"release-host-cli-auth-contract-unverified\"}\\' > codex-for-claude-review.json', `          printf '%s\\\\n' '{\"status\":\"preview\",\"reason\":\"release-host-cli-auth-contract-unverified\"}' > codex-for-claude-review.json\\n          steps:\\n${detectorBlock.replaceAll('      ', '            ')}`);"
        "process.stdout.write(JSON.stringify({reviewUngated:g.validateWorkflow(reviewUngated), installUngated:g.validateWorkflow(installUngated), extraUngated:g.validateWorkflow(extraUngated), extraGated:g.validateWorkflow(extraGated), disguisedUngated:g.validateWorkflow(disguisedUngated), extraJob:g.validateWorkflow(extraJob), quotedExtraJob:g.validateWorkflow(quotedExtraJob), shorthandUngated:g.validateWorkflow(shorthandUngated), unsafeDetector:g.validateWorkflow(unsafeDetector), unsafeDetectorAfterFi:g.validateWorkflow(unsafeDetectorAfterFi), duplicateDetector:g.validateWorkflow(duplicateDetector), duplicateExactDetector:g.validateWorkflow(duplicateExactDetector), scriptBodyStepsDetector:g.validateWorkflow(scriptBodyStepsDetector)}));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    review_check = next(check for check in payload["reviewUngated"]["checks"] if check["name"] == "fork-safe-step-gates")
    install_check = next(check for check in payload["installUngated"]["checks"] if check["name"] == "fork-safe-step-gates")
    extra_check = next(check for check in payload["extraUngated"]["checks"] if check["name"] == "fork-safe-step-gates")
    extra_gated_check = next(check for check in payload["extraGated"]["checks"] if check["name"] == "fork-safe-step-gates")
    disguised_check = next(check for check in payload["disguisedUngated"]["checks"] if check["name"] == "fork-safe-step-gates")
    extra_job_check = next(check for check in payload["extraJob"]["checks"] if check["name"] == "single-codex-review-job")
    quoted_extra_job_check = next(check for check in payload["quotedExtraJob"]["checks"] if check["name"] == "single-codex-review-job")
    shorthand_check = next(check for check in payload["shorthandUngated"]["checks"] if check["name"] == "fork-safe-step-gates")
    detector_check = next(check for check in payload["unsafeDetector"]["checks"] if check["name"] == "fork-safe-step-gates")
    detector_after_fi_check = next(check for check in payload["unsafeDetectorAfterFi"]["checks"] if check["name"] == "fork-safe-step-gates")
    duplicate_detector_check = next(check for check in payload["duplicateDetector"]["checks"] if check["name"] == "fork-safe-step-gates")
    duplicate_exact_detector_check = next(check for check in payload["duplicateExactDetector"]["checks"] if check["name"] == "fork-safe-step-gates")
    script_body_steps_detector_check = next(check for check in payload["scriptBodyStepsDetector"]["checks"] if check["name"] == "fork-safe-step-gates")
    assert review_check["ok"] is False
    assert install_check["ok"] is False
    assert extra_check["ok"] is False
    assert extra_gated_check["ok"] is False
    assert disguised_check["ok"] is False
    assert extra_job_check["ok"] is False
    assert quoted_extra_job_check["ok"] is False
    assert shorthand_check["ok"] is False
    assert detector_check["ok"] is False
    assert detector_after_fi_check["ok"] is False
    assert duplicate_detector_check["ok"] is False
    assert duplicate_exact_detector_check["ok"] is False
    assert script_body_steps_detector_check["ok"] is False
    assert payload["reviewUngated"]["structuralOk"] is False
    assert payload["installUngated"]["structuralOk"] is False
    assert payload["extraUngated"]["structuralOk"] is False
    assert payload["extraGated"]["structuralOk"] is False
    assert payload["disguisedUngated"]["structuralOk"] is False
    assert payload["extraJob"]["structuralOk"] is False
    assert payload["quotedExtraJob"]["structuralOk"] is False
    assert payload["shorthandUngated"]["structuralOk"] is False
    assert payload["unsafeDetector"]["structuralOk"] is False
    assert payload["unsafeDetectorAfterFi"]["structuralOk"] is False
    assert payload["duplicateDetector"]["structuralOk"] is False
    assert payload["duplicateExactDetector"]["structuralOk"] is False
    assert payload["scriptBodyStepsDetector"]["structuralOk"] is False


def test_codex_github_actions_validate_command_allows_preview_structural_workflow():
    result = run_node(
        PLUGIN / "scripts" / "codex-companion.mjs",
        ["github-actions", "validate", "--ref", "v0.2.0", "--json"],
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["structuralOk"] is True
    if payload["preview"]:
        assert payload["ready"] is False
        assert payload["ok"] is False


def test_codex_github_actions_init_writes_and_respects_force(tmp_path):
    result = run_node(
        PLUGIN / "scripts" / "codex-companion.mjs",
        ["github-actions", "init", "--ref", "v0.2.0"],
        cwd=tmp_path,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    workflow = tmp_path / ".github" / "workflows" / "codex-for-claude-review.yml"
    assert workflow.exists()
    text = read_text(workflow)
    assert "name: Codex for Claude Review" in text
    assert 'CODEX_FOR_CLAUDE_RELEASE_REF: "v0.2.0"' in text
    assert str(workflow) in result.stdout

    workflow.write_text("custom workflow\n", encoding="utf8")
    rejected = run_node(
        PLUGIN / "scripts" / "codex-companion.mjs",
        ["github-actions", "init", "--ref", "v0.2.0"],
        cwd=tmp_path,
        timeout=10,
    )
    assert rejected.returncode == 1
    assert "already exists" in rejected.stderr
    assert read_text(workflow) == "custom workflow\n"

    forced = run_node(
        PLUGIN / "scripts" / "codex-companion.mjs",
        ["github-actions", "init", "--ref", "v0.2.0", "--force"],
        cwd=tmp_path,
        timeout=10,
    )
    assert forced.returncode == 0, forced.stderr
    assert "name: Codex for Claude Review" in read_text(workflow)


def test_codex_github_actions_json_flag_is_validate_only(tmp_path):
    render = run_node(
        PLUGIN / "scripts" / "codex-companion.mjs",
        ["github-actions", "render", "--json"],
        cwd=tmp_path,
        timeout=10,
    )
    assert render.returncode == 1
    assert "--json is only supported for validate" in render.stderr
    init = run_node(
        PLUGIN / "scripts" / "codex-companion.mjs",
        ["github-actions", "init", "--json"],
        cwd=tmp_path,
        timeout=10,
    )
    assert init.returncode == 1
    assert "--json is only supported for validate" in init.stderr
    validate = run_node(
        PLUGIN / "scripts" / "codex-companion.mjs",
        ["github-actions", "validate", "--json"],
        cwd=tmp_path,
        timeout=10,
    )
    assert validate.returncode == 0, validate.stderr
    assert json.loads(validate.stdout)["structuralOk"] is True


def test_codex_role_packs_define_default_roles():
    script = (
        "const r = await import('./plugins/codex/scripts/lib/role-packs.mjs');"
        "process.stdout.write(JSON.stringify(r.resolveRoles({rolePack:'default'})));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    roles = json.loads(result.stdout)
    assert [role["id"] for role in roles] == ["correctness", "security", "tests", "release", "adversarial"]


def test_codex_role_packs_keep_security_guards_for_future_file_packs():
    source = read_text(PLUGIN / "scripts" / "lib" / "role-packs.mjs")
    assert "FORBIDDEN_FIELDS" in source
    assert "MAX_PACK_BYTES" in source
    assert "MAX_NESTING_DEPTH" in source
    assert "NAME_PATTERN" in source
    for forbidden in ["tools", "command", "hooks", "env", "provider", "max_effort"]:
        assert forbidden in source


def test_codex_quality_policy_is_available_before_multi_review_wiring():
    script = (
        "const q = await import('./plugins/codex/scripts/lib/quality-policy.mjs');"
        "process.stdout.write(JSON.stringify([q.resolveQuality('fast'), q.resolveQuality('standard'), q.resolveQuality('max')]));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    fast, standard, maxq = json.loads(result.stdout)
    assert fast["effort"] == "low"
    assert standard["effort"] == "medium"
    assert maxq["effort"] == "high"
    assert maxq["nativeReviewEffect"] == "metadata-only"


def test_codex_quality_policy_maps_presets_to_effort_and_model():
    script = (
        "const q = await import('./plugins/codex/scripts/lib/quality-policy.mjs');"
        "process.stdout.write(JSON.stringify([q.resolveQuality('fast'), q.resolveQuality('standard'), q.resolveQuality('max')]));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    fast, standard, maxq = json.loads(result.stdout)
    assert fast["effort"] == "low"
    assert standard["effort"] == "medium"
    assert maxq["effort"] == "high"
    assert maxq["nativeReviewEffect"] == "metadata-only"


def test_codex_adversarial_review_quality_effort_is_forwarded_to_turn_start():
    script = (
        "const c = await import('./plugins/codex/scripts/codex-companion.mjs');"
        "const context = {repoRoot:process.cwd(), branch:'main', summary:'1 file changed', target:{label:'working tree', mode:'working-tree'}, content:'diff --git a/src/demo.js b/src/demo.js', changedFiles:['src/demo.js'], inputMode:'inline-diff', collectionGuidance:'working tree diff', fileCount:1, diffBytes:42};"
        "const options = c.buildAdversarialReviewTurnOptions(context, {model:'gpt-5', effort:'high'}, 'focus');"
        "process.stdout.write(JSON.stringify({effort:options.effort, model:options.model, sandbox:options.sandbox}));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {"effort": "high", "model": "gpt-5", "sandbox": "read-only"}


def test_codex_native_review_quality_is_metadata_summary_only():
    companion = read_text(PLUGIN / "scripts" / "codex-companion.mjs")
    review_doc = read_text(PLUGIN / "commands" / "review.md")
    assert "export function buildReviewJobMetadata(reviewName, target, quality = null)" in companion
    assert "quality=${quality.quality}" in companion
    assert "--quality" in review_doc
    assert "zero runtime effect on native review" in review_doc
    native_start = companion.index('if (reviewName === "Review")')
    adversarial_start = companion.index("const context = collectReviewContext(request.cwd, target);", native_start)
    native_block = companion[native_start:adversarial_start]
    assert native_start < adversarial_start
    assert "sourceThreadId" in native_block
    match = re.search(r"runAppServerReview\(\s*request\.cwd\s*,\s*\{(?P<options>.*?)\}\s*\)", native_block, re.S)
    assert match, "native review must still call runAppServerReview(request.cwd, options)"
    options_region = match.group("options")
    assert "target: reviewTarget" in options_region
    assert "model: request.model" in options_region
    assert "onProgress: request.onProgress" in options_region
    assert "quality" not in options_region
    assert "request.effort" not in options_region
    assert "effort:" not in native_block
    assert "request.effort" not in native_block


def test_codex_native_review_quality_summary_metadata_behavior():
    script = (
        "const c = await import('./plugins/codex/scripts/codex-companion.mjs');"
        "const metadata = c.buildReviewJobMetadata('Review', {label:'working tree'}, {quality:'strong'});"
        "const plain = c.buildReviewJobMetadata('Review', {label:'working tree'}, null);"
        "process.stdout.write(JSON.stringify({metadata, plain}));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["metadata"]["kind"] == "review"
    assert payload["metadata"]["summary"].endswith("quality=strong")
    assert payload["plain"]["summary"] == "Review working tree"


def test_codex_multi_review_command_exists_and_is_argument_safe():
    text = read_text(PLUGIN / "commands" / "multi-review.md")
    assert "disable-model-invocation" not in text
    assert "allowed-tools: Bash(node:*)" in text
    assert "${CLAUDE_PLUGIN_ROOT}/scripts/codex-companion.mjs" in text
    assert "multi-review" in text
    assert "Select exactly one companion invocation" in text
    assert "Return the command stdout verbatim" in text
    blocks = fenced_bash_blocks(text)
    assert len(blocks) == 1
    assert blocks[0].count("codex-companion.mjs") == 1
    assert "$ARGUMENTS" not in blocks[0]


def test_codex_multi_review_uses_role_prompt_tracking_and_leases():
    companion = read_text(PLUGIN / "scripts" / "codex-companion.mjs")
    assert 'loadPromptTemplate(ROOT_DIR, "multi-review-role")' in companion
    assert 'acquireResourceLease("model-call"' in companion
    assert "commandLease.release?.();" in companion
    assert "executeTaskRun({" in companion
    assert "runForegroundCommand(" in companion
    assert "resolveQuality(options.quality" in companion
    assert "roleJobId" not in companion
    assert "jobId: job.id" in companion
    assert "renderReviewContextForPrompt(context)" in companion
    assert "const status = Number.isFinite(Number(result.exitStatus)) ? Number(result.exitStatus) : 0" in companion
    render_start = companion.index("function renderReviewContextForPrompt")
    prompt_start = companion.index("function buildMultiReviewRolePrompt")
    assert render_start < prompt_start
    render_region = companion[render_start:prompt_start]
    assert "context.content" in render_region
    assert "context.mode ?? context.target?.mode" in render_region
    assert "context.details" not in render_region
    prompt_region = companion[prompt_start: companion.index("async function handleMultiReview", prompt_start)]
    assert "context.content" not in prompt_region
    assert "context.details" not in prompt_region
    execute_body = js_function_body(companion, "executeTaskRun")
    assert "withResourceLease(" not in execute_body
    assert "writeJobFile(" not in execute_body
    assert "upsertJob(" not in execute_body
    assert "effort: request.effort" in execute_body
    turn_index = execute_body.index("runAppServerTurn(")
    assert "effort: request.effort" in execute_body[turn_index:]
    assert "if (request.resumeLast)" in execute_body
    assert "await resolveLatestTrackedTaskThread(workspaceRoot" in execute_body
    assert "excludeJobId: request.jobId" in execute_body
    assert "No previous Codex task thread was found" in execute_body
    assert "resumeThreadId = latestThread.id" in execute_body
    assert "defaultPrompt: resumeThreadId ? DEFAULT_CONTINUE_PROMPT : \"\"" in execute_body
    assert ": null" in execute_body
    assert "persistThread: request.persistThread !== false" in execute_body
    assert "persistThread: true" not in execute_body
    assert "request.persistThread === false ? null : (resumeThreadId ? null : buildPersistentTaskThreadName" in execute_body
    multi_start = companion.index("async function handleMultiReview")
    multi_body = companion[multi_start: companion.index("async function main", multi_start)]
    assert "executeTaskRun({" in multi_body
    assert "const model = normalizeRequestedModel(options.model)" in multi_body
    assert "model," in multi_body
    assert "effort: quality.effort" in multi_body
    assert "model: options.model" not in multi_body
    assert "resumeLast: false" in multi_body
    assert "persistThread: false" in multi_body
    assert "} catch (error) {" in multi_body
    assert "redactMachinePaths(error instanceof Error ? error.message : String(error))" in multi_body
    assert "output: `Role failed: ${message}`" in multi_body
    assert "error: message" in multi_body
    assert multi_body.index("redactMachinePaths(") < multi_body.index("output: `Role failed: ${message}`")
    assert multi_start < companion.index("async function main")


def test_codex_multi_review_role_prompt_renders_real_context():
    script = """
      const c = await import('./plugins/codex/scripts/codex-companion.mjs');
      const prompt = c.buildMultiReviewRolePrompt(
        {
          target: {label: 'working tree'},
          mode: 'working-tree',
          repoRoot: '<repo>',
          branch: 'main',
          summary: 'Reviewing 1 staged file.',
          inputMode: 'inline-diff',
          collectionGuidance: 'Use the inline diff as primary evidence.',
          fileCount: 1,
          diffBytes: 42,
          changedFiles: ['src/demo.js'],
          content: 'diff --git a/src/demo.js b/src/demo.js'
        },
        {title: 'Correctness', focus: 'Find behavior bugs.'}
      );
      process.stdout.write(prompt);
    """
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    assert "Reviewing 1 staged file." in result.stdout
    assert "Input mode: inline-diff" in result.stdout
    assert "Target mode: working-tree" in result.stdout
    assert "Use the inline diff as primary evidence." in result.stdout
    assert "diff --git a/src/demo.js b/src/demo.js" in result.stdout
    assert "undefined" not in result.stdout


def test_codex_multi_review_rejects_unsupported_flags():
    result = run_node(PLUGIN / "scripts" / "codex-companion.mjs", ["multi-review", "--bad"], timeout=10)
    assert result.returncode == 1
    assert "Unsupported option" in result.stderr


def test_codex_multi_review_capacity_zero_returns_capacity_blocked(tmp_path):
    git_marker = tmp_path / "git-was-called"
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    write_executable(
        fake_bin / "git",
        "#!/bin/sh\n"
        f"printf 'git called\\n' > {git_marker}\n"
        "exit 97\n",
    )
    result = subprocess.run(
        [NODE, str(PLUGIN / "scripts" / "codex-companion.mjs"), "multi-review", "--json"],
        cwd=tmp_path,
        env={
            **os.environ,
            "PATH": str(fake_bin),
            "CODEX_FOR_CLAUDE_RESOURCE_LOCK_DIR": str(tmp_path / "locks"),
            "CODEX_FOR_CLAUDE_GLOBAL_MAX_MODEL_CALLS": "0",
        },
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    assert result.returncode == 75
    assert "capacity_blocked" in result.stderr + result.stdout
    assert str(tmp_path) not in result.stderr + result.stdout
    assert not git_marker.exists()


def test_codex_multi_review_capacity_lease_precedes_git_and_context_collection():
    companion = read_text(PLUGIN / "scripts" / "codex-companion.mjs")
    body = js_function_body(companion, "handleMultiReview")
    lease_start = body.index('const commandLease = acquireResourceLease("model-call"')
    finally_index = body.index("finally {", lease_start)
    lease_region = body[lease_start:finally_index]
    assert lease_region.index('acquireResourceLease("model-call"') < lease_region.index("try {")
    assert lease_region.index("try {") < lease_region.index("resolveCommandWorkspace(options)")
    assert lease_region.index("resolveCommandWorkspace(options)") < lease_region.index("resolveReviewTarget(cwd")
    assert lease_region.index("try {") < lease_region.index("resolveReviewTarget(cwd")
    assert lease_region.index("resolveReviewTarget(cwd") < lease_region.index("createCompanionJob({")
    assert lease_region.index("createCompanionJob({") < lease_region.index("runForegroundCommand(")
    assert lease_region.index("runForegroundCommand(") < lease_region.index("collectReviewContext(cwd")


def test_codex_release_check_import_is_side_effect_free_after_github_actions_import():
    script = "await import('./plugins/codex/scripts/lib/release-check.mjs');"
    result = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_codex_github_actions_module_has_no_top_level_side_effects():
    source = read_text(PLUGIN / "scripts" / "lib" / "github-actions.mjs")
    first_function = min(index for index in [
        source.index("export function renderWorkflow"),
        source.index("export function validateWorkflow"),
    ] if index >= 0)
    top_level_region = source[:first_function]
    for forbidden in ["fs.readFileSync(", "spawnSync(", "console.", "process.stdout", "process.stderr", "await "]:
        assert forbidden not in top_level_region
    assert "const PLUGIN_ROOT" in top_level_region


def test_codex_github_actions_plugin_root_resolves_template_from_installed_cache_layout(tmp_path):
    installed = tmp_path / "cache" / "external-models-for-claude" / "codex" / "1.1.0-fh.2"
    shutil.copytree(PLUGIN, installed)
    module_url = (installed / "scripts" / "lib" / "github-actions.mjs").as_uri()
    script = (
        "const moduleUrl = process.argv[1];"
        "const g = await import(moduleUrl);"
        "const text = g.renderWorkflow({ref:'v0.2.0'});"
        "process.stdout.write(JSON.stringify({hasTemplate:text.includes('name: Codex for Claude Review'), hasRootResolver:text.includes('codex-plugin-root-resolver-begin'), validation:g.validateWorkflow(text)}));"
    )
    result = subprocess.run([NODE, "--input-type=module", "-e", script, module_url], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["hasTemplate"] is True
    assert payload["hasRootResolver"] is True
    assert any(check["name"] == "plugin-root-resolved" and check["ok"] is True for check in payload["validation"]["checks"])


def test_codex_github_actions_rendered_yaml_parses_when_parser_available():
    ruby = shutil.which("ruby")
    if not ruby:
        pytest.skip("ruby YAML parser unavailable")
    result = run_node(PLUGIN / "scripts" / "codex-companion.mjs", ["github-actions", "render", "--ref", "v0.2.0"], timeout=10)
    assert result.returncode == 0, result.stderr
    for placeholder in ["{{RELEASE_REF}}", "{{CODEX_CLI_NPM_VERSION}}", "{{CLAUDE_CODE_NPM_VERSION}}", "{{CODEX_AUTH_STEPS}}", "{{CODEX_REVIEW_STEP}}"]:
        assert placeholder not in result.stdout
    parse = subprocess.run(
        [ruby, "-e", "require 'yaml'; YAML.safe_load(STDIN.read, permitted_classes: [], aliases: false)"],
        input=result.stdout,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert parse.returncode == 0, parse.stderr


def test_codex_github_actions_rendered_yaml_has_basic_structure_without_ruby():
    result = run_node(PLUGIN / "scripts" / "codex-companion.mjs", ["github-actions", "render", "--ref", "v0.2.0"], timeout=10)
    assert result.returncode == 0, result.stderr
    text = result.stdout
    for placeholder in ["{{RELEASE_REF}}", "{{CODEX_CLI_NPM_VERSION}}", "{{CLAUDE_CODE_NPM_VERSION}}", "{{CODEX_AUTH_STEPS}}", "{{CODEX_REVIEW_STEP}}"]:
        assert placeholder not in text
    assert "jobs:\n  codex-review:" in text
    assert "\n    steps:\n" in text
    assert text.count("- name:") >= 6
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        assert indent % 2 == 0, line


def test_codex_github_actions_rejects_mutable_ref():
    result = run_node(PLUGIN / "scripts" / "codex-companion.mjs", ["github-actions", "render", "--ref", "main"], timeout=10)
    assert result.returncode == 1
    assert "immutable version tag" in result.stderr


def test_codex_github_actions_rejects_unsupported_flags():
    result = run_node(PLUGIN / "scripts" / "codex-companion.mjs", ["github-actions", "render", "--bad"], timeout=10)
    assert result.returncode == 1
    assert "Unsupported option" in result.stderr


def test_codex_release_check_ci_simulate_validates_workflow():
    result = run_node(PLUGIN / "scripts" / "codex-companion.mjs", ["release-check", "--ci-simulate", "--json"], timeout=20)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    names = {check["name"] for check in payload["checks"]}
    assert {
        "ci-workflow-validation",
        "ci-workflow-fork-safe",
        "ci-workflow-codex-auth-login",
        "ci-workflow-codex-cli-version-pinned",
        "ci-workflow-claude-code-version-pinned",
        "ci-workflow-plugin-root-resolved",
        "ci-claude-code-version-contract",
        "ci-codex-cli-version-contract",
        "ci-codex-cli-auth-contract",
    } <= names
    version_contract = next(check for check in payload["checks"] if check["name"] == "ci-codex-cli-version-contract")
    assert "verified" in version_contract["detail"] or "not verified" in version_contract["detail"]


def test_codex_release_check_ci_simulate_fails_invalid_workflow_validator_checks(tmp_path):
    repo = copy_repo(tmp_path)
    template = repo / "plugins" / "codex" / "templates" / "github-actions" / "codex-review.yml"
    template.write_text(
        read_text(template).replace("permissions:\n  contents: read", "permissions:\n  contents: read\n  pull-requests: write"),
        encoding="utf8",
    )
    result = run_node(
        repo / "plugins" / "codex" / "scripts" / "codex-companion.mjs",
        ["release-check", "--ci-simulate", "--json"],
        cwd=repo,
        timeout=20,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    assert payload["ok"] is False
    assert checks["ci-workflow-validation"]["ok"] is False
    assert "minimal-contents-permission" in json.dumps(checks["ci-workflow-validation"]["detail"])


def test_codex_release_check_ci_simulate_rejects_preview_review_injection(tmp_path):
    repo = copy_repo(tmp_path)
    template = repo / "plugins" / "codex" / "templates" / "github-actions" / "codex-review.yml"
    template.write_text(
        read_text(template).replace(
            "{{CODEX_REVIEW_STEP}}",
            '      - name: Injected Codex review\n'
            '        run: node "$CLAUDE_PLUGIN_ROOT/scripts/codex-companion.mjs" review --base "$BASE_SHA" --json\n'
            "{{CODEX_REVIEW_STEP}}",
        ),
        encoding="utf8",
    )
    result = run_node(
        repo / "plugins" / "codex" / "scripts" / "codex-companion.mjs",
        ["release-check", "--ci-simulate", "--json"],
        cwd=repo,
        timeout=20,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    assert checks["ci-workflow-validation"]["ok"] is False
    assert "codex-review-step" in json.dumps(checks["ci-workflow-validation"]["detail"])


def test_codex_release_check_ci_simulate_auth_contract_is_advisory_without_require_flag():
    result = run_node(
        PLUGIN / "scripts" / "codex-companion.mjs",
        ["release-check", "--ci-simulate", "--json"],
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    contract = next(check for check in payload["checks"] if check["name"] == "ci-codex-cli-auth-contract")
    assert contract["ok"] is True
    assert "not verified" in contract["detail"]
    assert "--require-codex-cli" in contract["detail"]
    source = read_text(PLUGIN / "scripts" / "lib" / "release-check.mjs")
    body = js_function_body(source, "runReleaseCheck")
    require_region = body[body.index("if (requireCodexCli)"):]
    pre_require_region = body[:body.index("if (requireCodexCli)")]
    assert "spawnSync(" not in pre_require_region
    assert "spawnSync(" in require_region


def test_codex_release_check_require_flag_rejects_unresolved_version_sentinels():
    script = (
        "const g = await import('./plugins/codex/scripts/lib/github-actions.mjs');"
        "process.stdout.write(JSON.stringify({codex:g.CODEX_CLI_NPM_VERSION, claude:g.CLAUDE_CODE_NPM_VERSION}));"
    )
    constants = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert constants.returncode == 0, constants.stderr
    versions = json.loads(constants.stdout)
    if not (versions["codex"].startswith("REPLACE_WITH_") or versions["claude"].startswith("REPLACE_WITH_")):
        pytest.skip("release-host version sentinels were already replaced")
    result = run_node(
        PLUGIN / "scripts" / "codex-companion.mjs",
        ["release-check", "--ci-simulate", "--require-codex-cli", "--json"],
        timeout=20,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    details = {check["name"]: check["detail"] for check in payload["checks"]}
    assert "sentinel not replaced" in details["ci-claude-code-version-contract"] or "sentinel not replaced" in details["ci-codex-cli-version-contract"]


def test_codex_release_check_require_flag_implies_ci_simulate():
    script = (
        "const g = await import('./plugins/codex/scripts/lib/github-actions.mjs');"
        "process.stdout.write(JSON.stringify({codex:g.CODEX_CLI_NPM_VERSION, claude:g.CLAUDE_CODE_NPM_VERSION}));"
    )
    constants = subprocess.run([NODE, "--input-type=module", "-e", script], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    assert constants.returncode == 0, constants.stderr
    versions = json.loads(constants.stdout)
    if not (versions["codex"].startswith("REPLACE_WITH_") or versions["claude"].startswith("REPLACE_WITH_")):
        pytest.skip("release-host version sentinels were already replaced")
    result = run_node(
        PLUGIN / "scripts" / "codex-companion.mjs",
        ["release-check", "--require-codex-cli", "--json"],
        timeout=20,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    names = {check["name"] for check in payload["checks"]}
    assert "ci-workflow-validation" in names
    details = {check["name"]: check["detail"] for check in payload["checks"]}
    assert "sentinel not replaced" in details["ci-claude-code-version-contract"] or "sentinel not replaced" in details["ci-codex-cli-version-contract"]


def test_codex_release_check_require_flag_verifies_stdin_login_contract(tmp_path):
    repo = copy_repo(tmp_path)
    github_actions = repo / "plugins" / "codex" / "scripts" / "lib" / "github-actions.mjs"
    text = read_text(github_actions)
    text = text.replace(
        'export const CODEX_CLI_NPM_VERSION = "REPLACE_WITH_RELEASE_HOST_CODEX_CLI_VERSION";',
        'export const CODEX_CLI_NPM_VERSION = "1.2.3";',
    ).replace(
        'export const CLAUDE_CODE_NPM_VERSION = "REPLACE_WITH_RELEASE_HOST_CLAUDE_CODE_VERSION";',
        'export const CLAUDE_CODE_NPM_VERSION = "4.5.6";',
    ).replace(
        "export const RELEASE_HOST_CONTRACTS_VERIFIED = false;",
        "export const RELEASE_HOST_CONTRACTS_VERIFIED = true;",
    )
    github_actions.write_text(text, encoding="utf8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    write_executable(
        bin_dir / "npm",
        "#!/bin/sh\n"
        "if [ \"$1\" = \"view\" ] && [ \"$3\" = \"version\" ]; then\n"
        "  case \"$2\" in\n"
        "    @openai/codex@1.2.3) printf '1.2.3\\n'; exit 0 ;;\n"
        "    @anthropic-ai/claude-code@4.5.6) printf '4.5.6\\n'; exit 0 ;;\n"
        "  esac\n"
        "fi\n"
        "printf 'unexpected npm args: %s\\n' \"$*\" >&2\n"
        "exit 1\n",
    )
    write_executable(
        bin_dir / "codex",
        "#!/bin/sh\n"
        "if [ \"$1\" = \"login\" ] && [ \"$2\" = \"--help\" ]; then\n"
        "  printf 'Usage: codex login --with-api-key\\n'\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"login\" ] && [ \"$2\" = \"--with-api-key\" ]; then\n"
        "  read api_key\n"
        "  printf 'stdin login rejected: %s\\n' \"$api_key\" >&2\n"
        "  exit 42\n"
        "fi\n"
        "printf 'unexpected codex args: %s\\n' \"$*\" >&2\n"
        "exit 1\n",
    )
    result = run_node(
        repo / "plugins" / "codex" / "scripts" / "codex-companion.mjs",
        ["release-check", "--require-codex-cli", "--json"],
        cwd=repo,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "OPENAI_API_KEY": "fake-release-key",
        },
        timeout=20,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    assert checks["ci-codex-cli-version-contract"]["ok"] is True
    assert checks["ci-codex-cli-auth-contract"]["ok"] is False
    assert "stdin" in checks["ci-codex-cli-auth-contract"]["detail"]
    write_executable(
        bin_dir / "codex",
        "#!/bin/sh\n"
        "if [ \"$1\" = \"login\" ] && [ \"$2\" = \"--help\" ]; then\n"
        "  printf 'Usage: codex login --with-api-key\\n'\n"
        "  exit 0\n"
        "fi\n"
        "if [ \"$1\" = \"login\" ] && [ \"$2\" = \"--with-api-key\" ]; then\n"
        "  read api_key\n"
        "  test \"$api_key\" = \"fake-release-key\"\n"
        "  exit $?\n"
        "fi\n"
        "printf 'unexpected codex args: %s\\n' \"$*\" >&2\n"
        "exit 1\n",
    )
    success = run_node(
        repo / "plugins" / "codex" / "scripts" / "codex-companion.mjs",
        ["release-check", "--require-codex-cli", "--json"],
        cwd=repo,
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "OPENAI_API_KEY": "fake-release-key",
        },
        timeout=20,
    )
    assert success.returncode == 0, success.stderr
    success_payload = json.loads(success.stdout)
    success_checks = checks_by_name(success_payload)
    assert success_checks["ci-codex-cli-auth-contract"]["ok"] is True
    assert "stdin contract" in success_checks["ci-codex-cli-auth-contract"]["detail"]


def test_codex_release_check_has_concrete_preview_command_surface():
    source = read_text(PLUGIN / "scripts" / "lib" / "release-check.mjs")
    assert "const EXPECTED_COMMANDS" in source
    assert "const PREVIEW_COMMANDS" in source
    assert "const READY_COMMANDS" in source
    assert "ready-command-surface" in source
    assert 'new Set(["github-actions.md"])' in source


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
