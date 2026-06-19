import json
import os
import pathlib
import re
import shutil
import subprocess

from plugin_versions import CODEX_VERSION, MARKETPLACE_VERSION


ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex"
NODE = os.environ.get("NODE_BINARY") or shutil.which("node") or "node"

MARKETPLACE_CODEX_AUTHOR = {
    "name": "OpenAI",
    "url": "https://github.com/openai/codex-plugin-cc",
}
PLUGIN_CODEX_AUTHOR = {"name": "OpenAI"}
DEFAULT_EXPECT_MARKETPLACE_ENTRY_VERSION = True


def read_json(path):
    return json.loads(path.read_text(encoding="utf8"))


def read_text(path):
    return path.read_text(encoding="utf8")


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


MACHINE_PATH_PATTERN = load_machine_path_pattern()


def should_expect_marketplace_entry_version(root):
    evidence_path = root / "plugins" / "codex" / "VERSION_AXIS_CONFIRMATION.md"
    if not evidence_path.exists():
        return DEFAULT_EXPECT_MARKETPLACE_ENTRY_VERSION
    evidence = read_text(evidence_path)
    if "marketplaceEntryVersionSupported: true" in evidence:
        return True
    if "marketplaceEntryVersionSupported: false" in evidence:
        return False
    return DEFAULT_EXPECT_MARKETPLACE_ENTRY_VERSION


EXPECT_MARKETPLACE_ENTRY_VERSION = should_expect_marketplace_entry_version(ROOT)


def assert_no_machine_paths(text):
    assert not MACHINE_PATH_PATTERN.search(text)


def test_codex_plugin_is_local_fork_with_openai_attribution():
    marketplace = read_json(ROOT / ".claude-plugin" / "marketplace.json")
    manifest = read_json(PLUGIN / ".claude-plugin" / "plugin.json")
    plugin_entry = {item["name"]: item for item in marketplace["plugins"]}["codex"]

    assert marketplace["metadata"]["version"] == MARKETPLACE_VERSION
    if EXPECT_MARKETPLACE_ENTRY_VERSION:
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


def test_machine_path_pattern_catches_common_local_path_shapes():
    positives = [
        "/Users/fanghao/Documents/Claude for codex",
        "/home/alice/project",
        "/private/var/folders/p6/mbyd_p7d1md2wcqhq2g07tw00000gn/T/repo",
        "/var/folders/p6/mbyd_p7d1md2wcqhq2g07tw00000gn/T/repo",
        r"C:\Users\Jane Doe\AppData\Local\Temp\repo",
        "C:/Users/Jane Doe/AppData/Local/Temp/repo",
    ]
    negatives = [
        "/home/runner/work/external-models-for-claude",
        "/home/vscode/workspace",
        "/home/ubuntu/project",
        "/home/circleci/project",
        "/home/runneradmin/project",
    ]
    for text in positives:
        assert MACHINE_PATH_PATTERN.search(text), text
    for text in negatives:
        assert not MACHINE_PATH_PATTERN.search(text), text
