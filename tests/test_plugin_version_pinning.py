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


class GitUnavailable(RuntimeError):
    """A git query the guard depends on failed, so its answer cannot be trusted."""


def _git(*args, allow_failure=False):
    """Run git and FAIL LOUD on error.

    Collapsing a nonzero exit into an empty string is what makes this class of
    guard fail open: a broken ``git log`` would look like "nothing changed" and
    the suite would go green on an unverified repository. Only callers that can
    genuinely distinguish "absent" from "broken" pass ``allow_failure``.
    """
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        if allow_failure:
            return None
        raise GitUnavailable(
            f"git {' '.join(args)} failed ({result.returncode}): {result.stderr.strip() or 'no stderr'}"
        )
    return result.stdout.strip()


def _plugin_dirs():
    return sorted(p for p in (ROOT / "plugins").iterdir() if (p / ".claude-plugin" / "plugin.json").exists())


def _version_of(plugin_dir):
    manifest = plugin_dir / ".claude-plugin" / "plugin.json"
    return json.loads(manifest.read_text(encoding="utf8"))["version"]


def _manifest_rel(plugin_dir):
    return str((plugin_dir / ".claude-plugin" / "plugin.json").relative_to(ROOT))


#: Marks a commit at which the plugin's manifest did not exist. Distinct from a
#: version string so that delete-then-readd shows up as a real gap in the history
#: rather than silently welding two runs of the same version together.
ABSENT = "<absent>"


def _version_at(commit, manifest_rel):
    # A missing path is a legitimate answer (the plugin did not exist yet, or was
    # deleted), so this is the one place a git failure is allowed — and it is
    # still distinguished from a malformed manifest below.
    blob = _git("show", f"{commit}:{manifest_rel}", allow_failure=True)
    if blob is None or not blob:
        return ABSENT
    try:
        return json.loads(blob)["version"]
    except (json.JSONDecodeError, KeyError) as error:
        raise GitUnavailable(
            f"manifest at {commit[:8]}:{manifest_rel} is unreadable ({error}); "
            "the version-pinning guard cannot judge this history"
        ) from error


def _released_ref():
    """The ref representing already-released bytes.

    Drift only matters once bytes are published, and a branch's own commits are a
    single release unit: bumping in one commit and editing the payload in the next
    is normal and squash-merges into one commit on main. So history is judged
    against ``origin/main`` and the branch is judged as a whole against it. Falls
    back to HEAD when there is no remote (fresh clone, detached CI checkout), which
    degrades to judging local history only — never to skipping the check.
    """
    for ref in ("origin/main", "main"):
        if _git("rev-parse", "--verify", "--quiet", ref, allow_failure=True):
            return ref
    return "HEAD"


def _manifest_version_history(plugin_dir, ref="HEAD"):
    """[(commit, version)] newest-first, for every commit touching the manifest.

    Reading the version *value* at each commit is deliberate. ``git log -S`` was
    tried first and is wrong here: it matches any change to how often a string
    occurs, so a rollback (0.1.1 -> 0.1.2 -> 0.1.1) or a reformat of the version
    line becomes the newest match and silently rebases the baseline onto it.
    """
    manifest_rel = _manifest_rel(plugin_dir)
    commits = [c for c in _git("log", "--format=%H", ref, "--", manifest_rel).splitlines() if c.strip()]
    return [(c, _version_at(c, manifest_rel)) for c in commits]


def _uncommitted_payload_changes(plugin_dir):
    """Tracked-or-untracked working-tree changes under the plugin, manifest aside.

    Checking only committed history would let a pre-commit run go green on edits
    that are about to ship: this repo's gate is a local pytest run, not CI, so an
    unbumped payload edit could pass review and land. ``--porcelain`` covers
    staged, unstaged and untracked paths in one query.
    """
    relative = str(plugin_dir.relative_to(ROOT))
    manifest_rel = _manifest_rel(plugin_dir)
    lines = _git("status", "--porcelain", "--", relative).splitlines()
    changed = []
    for line in lines:
        path = line[3:].strip().strip('"')
        # Renames read as "old -> new"; the destination is what ships.
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path and path != manifest_rel:
            changed.append(path)
    return sorted(set(changed))


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

    released = _released_ref()
    stale = {}
    for plugin_dir in plugin_dirs:
        version = _version_of(plugin_dir)
        relative = str(plugin_dir.relative_to(ROOT))
        released_version = _version_at(released, _manifest_rel(plugin_dir))

        # Everything not yet on the released ref -- this branch's commits plus the
        # working tree -- is one release unit. It only has to carry a version that
        # differs from what is already published.
        pending = _git("diff", "--name-only", released, "--", relative).splitlines()
        pending += _uncommitted_payload_changes(plugin_dir)
        if pending and released_version != ABSENT and version == released_version:
            stale[plugin_dir.name] = (
                version,
                [f"(pending vs {released}) {p.strip()}" for p in sorted(set(pending)) if p.strip()],
            )

    assert not stale, (
        "plugin bytes changed but the version did not — bump it, or installs keep the "
        "stale bytes under the same cache key:\n"
        + "\n".join(
            f"  {name} (still {version}) changed:\n"
            + "\n".join(f"    {line}" for line in changes)
            for name, (version, changes) in sorted(stale.items())
        )
    )


def test_no_plugin_version_is_ever_reused_for_a_second_set_of_bytes():
    """A version key must map to one set of bytes for all time.

    Rolling a version back (0.1.1 -> 0.1.2 -> 0.1.1) leaves the cache key 0.1.1
    pointing at two different trees, and whoever installed the first 0.1.1 keeps
    it forever. The newest run is checked above; this catches the reuse itself.
    """
    reused = {}
    for plugin_dir in _plugin_dirs():
        # ABSENT is kept in the sequence on purpose: a plugin that was deleted and
        # later re-added at the same version is reuse of that cache key, and
        # dropping the gap would weld the two runs into one and hide it. This repo
        # has already removed two plugins, so the path is not theoretical.
        seen_versions = [v for _, v in _manifest_version_history(plugin_dir)]
        # Collapse consecutive duplicates: one contiguous run is normal, two are reuse.
        runs = [v for i, v in enumerate(seen_versions) if i == 0 or seen_versions[i - 1] != v]
        # Every version ever published is a cache key, not just the current one:
        # 0.1.0 -> 0.1.1 -> 0.1.0 -> 0.1.2 already stranded two trees under 0.1.0
        # even though 0.1.2 is what ships today.
        # ABSENT recurring just means the plugin was removed more than once; only a
        # real version string recurring strands a cache key.
        offenders = sorted({v for v in runs if v != ABSENT and runs.count(v) > 1})
        if offenders:
            reused[plugin_dir.name] = offenders

    assert not reused, "a version string was reused after being replaced — pick a new version:\n" + "\n".join(
        f"  {name}: {', '.join(versions)} each appear in more than one run of its manifest history"
        for name, versions in sorted(reused.items())
    )


def test_marketplace_entry_versions_match_each_plugin_manifest():
    """A bump must reach the marketplace entry too, or installs resolve the old key."""
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf8"))

    for plugin_dir in _plugin_dirs():
        name = plugin_dir.name
        # Collect rather than index by name: a dict would keep only the last
        # duplicate, so a stale second entry could hide behind a matching one.
        matching = [item for item in marketplace["plugins"] if item["name"] == name]
        assert len(matching) == 1, (
            f"{name}: expected exactly one marketplace entry, found {len(matching)} "
            f"(versions: {[item.get('version') for item in matching]})"
        )
        assert matching[0]["version"] == _version_of(plugin_dir), (
            f"{name}: marketplace entry says {matching[0]['version']} but its manifest says "
            f"{_version_of(plugin_dir)}"
        )
