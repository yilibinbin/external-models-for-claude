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

The rule enforced here: **the bytes under ``plugins/<name>/`` must not have
changed since that plugin's current version was set, and a version string must
never be reused for a second set of bytes.**
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


def _manifest_rel(plugin_dir):
    return str((plugin_dir / ".claude-plugin" / "plugin.json").relative_to(ROOT))


def _version_at(commit, manifest_rel):
    blob = _git("show", f"{commit}:{manifest_rel}")
    if not blob:
        return None
    try:
        return json.loads(blob)["version"]
    except (json.JSONDecodeError, KeyError):
        return None


def _manifest_version_history(plugin_dir):
    """[(commit, version)] newest-first, for every commit touching the manifest.

    Reading the version *value* at each commit is deliberate. ``git log -S`` was
    tried first and is wrong here: it matches any change to how often a string
    occurs, so a rollback (0.1.1 -> 0.1.2 -> 0.1.1) or a reformat of the version
    line becomes the newest match and silently rebases the baseline onto it.
    """
    manifest_rel = _manifest_rel(plugin_dir)
    commits = [c for c in _git("log", "--format=%H", "--", manifest_rel).splitlines() if c.strip()]
    return [(c, _version_at(c, manifest_rel)) for c in commits]


def _commits_touching_since(plugin_dir, commit):
    relative = str(plugin_dir.relative_to(ROOT))
    out = _git("log", "--format=%H %s", f"{commit}..HEAD", "--", relative)
    return [line for line in out.splitlines() if line.strip()]


def _manifest_differs_from_head(plugin_dir):
    """True when the manifest carries an uncommitted edit (a bump in progress)."""
    return bool(_git("diff", "HEAD", "--name-only", "--", _manifest_rel(plugin_dir)))


def test_repository_history_is_deep_enough_to_judge_version_pinning():
    """A shallow checkout hides drift older than its cutoff, so refuse to judge.

    Measured: a ``--depth 1`` clone of a main that genuinely carried unbumped
    codex and review-chain bytes reported both clean, because the truncation
    point looks like the commit that introduced every current version. Passing
    vacuously in the common CI checkout shape is worse than not running at all.
    """
    assert _git("rev-parse", "--is-shallow-repository") == "false", (
        "shallow checkout: the version-pinning guard cannot see drift older than the "
        "clone's cutoff and would pass vacuously. Fetch full history "
        "(git fetch --unshallow, or actions/checkout with fetch-depth: 0)."
    )


def test_every_plugin_version_covers_its_shipped_bytes():
    plugin_dirs = _plugin_dirs()
    assert plugin_dirs, "no plugins discovered — the guard would pass vacuously"

    stale = {}
    for plugin_dir in plugin_dirs:
        version = _version_of(plugin_dir)
        history = _manifest_version_history(plugin_dir)
        current_run = []
        for commit, seen in history:
            if seen != version:
                break
            current_run.append(commit)

        if not current_run:
            # The version is in no commit yet. Legitimate exactly once: an
            # uncommitted bump in the working tree, which by definition covers
            # every pending change. Any other cause leaves the guard unable to
            # judge, so it fails rather than waving the plugin through.
            assert _manifest_differs_from_head(plugin_dir), (
                f"{plugin_dir.name}: version {version} appears in no commit and the manifest "
                "matches HEAD, so the guard cannot judge it"
            )
            continue

        # Oldest commit of the newest contiguous run = the commit that set this version.
        baseline = current_run[-1]
        later = _commits_touching_since(plugin_dir, baseline)
        if later:
            stale[plugin_dir.name] = (version, later)

    assert not stale, "plugin bytes changed after the version was set — bump the version:\n" + "\n".join(
        f"  {name} (still {version}) changed by:\n"
        + "\n".join(f"    {line}" for line in commits)
        for name, (version, commits) in sorted(stale.items())
    )


def test_no_plugin_version_is_ever_reused_for_a_second_set_of_bytes():
    """A version key must map to one set of bytes for all time.

    Rolling a version back (0.1.1 -> 0.1.2 -> 0.1.1) leaves the cache key 0.1.1
    pointing at two different trees, and whoever installed the first 0.1.1 keeps
    it forever. The newest run is checked above; this catches the reuse itself.
    """
    reused = {}
    for plugin_dir in _plugin_dirs():
        version = _version_of(plugin_dir)
        seen_versions = [v for _, v in _manifest_version_history(plugin_dir) if v is not None]
        # Collapse consecutive duplicates: one contiguous run is normal, two are reuse.
        runs = [v for i, v in enumerate(seen_versions) if i == 0 or seen_versions[i - 1] != v]
        if runs.count(version) > 1:
            reused[plugin_dir.name] = version

    assert not reused, "a version string was reused after being replaced — pick a new version:\n" + "\n".join(
        f"  {name}: {version} appears in more than one run of its manifest history"
        for name, version in sorted(reused.items())
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
