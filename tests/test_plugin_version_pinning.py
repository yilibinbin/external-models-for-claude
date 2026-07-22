"""Guard against shipping changed plugin bytes under an unchanged version key.

Claude Code installs a plugin into a *version-pinned* cache directory
(``~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/``) and the runtime
loads from there. So if a plugin's shipped files change while its version does
not, every existing install keeps the stale bytes: a fresh install and an
upgraded install then behave differently under the same version string, and a
fix silently does not apply.

This is not hypothetical. ``review-chain`` shipped a registry fix and a rewritten
SKILL under an unchanged ``0.1.0``; the installed copy kept the old bytes and the
fix had no effect locally until the plugin was uninstalled and reinstalled.

The rule these tests enforce: **if anything under ``plugins/<name>/`` changed
since that plugin's version was last set, the version must be bumped.**
"""

import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _git(*args):
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _plugin_dirs():
    return sorted(p for p in (ROOT / "plugins").iterdir() if (p / ".claude-plugin" / "plugin.json").exists())


def _version_of(plugin_dir):
    manifest = plugin_dir / ".claude-plugin" / "plugin.json"
    return json.loads(manifest.read_text(encoding="utf8"))["version"]


def _commit_that_set_version(plugin_dir, version):
    """The commit that introduced the current version string into plugin.json.

    ``-S`` matches commits that change how many times the string occurs, so this
    lands on the bump commit itself rather than on later edits to the manifest.
    """
    relative = (plugin_dir / ".claude-plugin" / "plugin.json").relative_to(ROOT)
    return _git("log", "-1", "--format=%H", "-S", f'"version": "{version}"', "--", str(relative))


def _commits_touching_since(plugin_dir, commit):
    relative = plugin_dir.relative_to(ROOT)
    out = _git("log", "--format=%H %s", f"{commit}..HEAD", "--", str(relative))
    return [line for line in out.splitlines() if line.strip()]


def _manifest_differs_from_head(plugin_dir):
    """True when the manifest carries an uncommitted edit (a bump in progress)."""
    relative = (plugin_dir / ".claude-plugin" / "plugin.json").relative_to(ROOT)
    return bool(_git("diff", "HEAD", "--name-only", "--", str(relative)))


def test_every_plugin_version_covers_its_shipped_bytes():
    plugin_dirs = _plugin_dirs()
    assert plugin_dirs, "no plugins discovered — the guard would pass vacuously"

    stale = {}
    for plugin_dir in plugin_dirs:
        version = _version_of(plugin_dir)
        bump_commit = _commit_that_set_version(plugin_dir, version)
        if not bump_commit:
            # The version is not in history yet. That is legitimate exactly once:
            # an uncommitted bump in the working tree, which by definition covers
            # every pending change to this plugin. Any other cause (shallow clone,
            # hand-edited history) leaves the guard unable to judge, so it fails
            # rather than waving the plugin through.
            assert _manifest_differs_from_head(plugin_dir), (
                f"{plugin_dir.name}: version {version} appears in no commit and the manifest "
                "matches HEAD, so the version-pinning guard cannot judge it; it needs the "
                "manifest's git history"
            )
            continue
        later = _commits_touching_since(plugin_dir, bump_commit)
        if later:
            stale[plugin_dir.name] = (version, later)

    assert not stale, "plugin bytes changed after the version was set — bump the version:\n" + "\n".join(
        f"  {name} (still {version}) changed by:\n"
        + "\n".join(f"    {line}" for line in commits)
        for name, (version, commits) in sorted(stale.items())
    )


def test_marketplace_entry_versions_match_each_plugin_manifest():
    """A bump must reach the marketplace entry too, or installs resolve the old key."""
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf8"))
    entries = {item["name"]: item for item in marketplace["plugins"]}

    for plugin_dir in _plugin_dirs():
        name = plugin_dir.name
        assert name in entries, f"{name} ships in plugins/ but has no marketplace entry"
        assert entries[name]["version"] == _version_of(plugin_dir), (
            f"{name}: marketplace entry says {entries[name]['version']} but its manifest says "
            f"{_version_of(plugin_dir)}"
        )
