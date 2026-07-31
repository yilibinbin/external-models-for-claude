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
import re
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
    # "The plugin did not exist at this commit" is a real answer, but it must be
    # established POSITIVELY -- by asking the tree what it contains -- and never
    # inferred from a failed read. A corrupt object or a partial clone would
    # otherwise make an existing released plugin look newly added, which exempts
    # it from enforcement.
    listing = _git("ls-tree", "--name-only", commit, "--", manifest_rel)
    if not listing:
        return ABSENT
    blob = _git("show", f"{commit}:{manifest_rel}")
    if not blob:
        raise GitUnavailable(
            f"{commit[:8]}:{manifest_rel} is listed in the tree but read back empty; "
            "the version-pinning guard cannot judge this history"
        )
    try:
        return json.loads(blob)["version"]
    except (json.JSONDecodeError, KeyError) as error:
        raise GitUnavailable(
            f"manifest at {commit[:8]}:{manifest_rel} is unreadable ({error}); "
            "the version-pinning guard cannot judge this history"
        ) from error


def _version_in_index(plugin_dir):
    """Manifest version as the index has it — what the next commit would record."""
    manifest_rel = _manifest_rel(plugin_dir)
    listing = _git("ls-files", "--", manifest_rel)
    if not listing:
        return ABSENT
    blob = _git("show", f":{manifest_rel}")
    if not blob:
        raise GitUnavailable(f"index entry for {manifest_rel} read back empty")
    try:
        return json.loads(blob)["version"]
    except (json.JSONDecodeError, KeyError) as error:
        raise GitUnavailable(f"index copy of {manifest_rel} is unreadable ({error})") from error


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


def _published_ref():
    """The ref whose bytes are already installed on other machines.

    This comparison has no meaning without it, so a missing base ref FAILS rather
    than falling back to HEAD: `git diff HEAD` is empty for committed work, which
    silently disables the whole guard on a detached checkout.
    """
    for ref in ("origin/main", "main"):
        if _git("rev-parse", "--verify", "--quiet", ref, allow_failure=True):
            return ref
    raise GitUnavailable(
        "no origin/main or main to compare against; the version-pinning guard needs a "
        "published base ref (git fetch origin main) and refuses to pass vacuously"
    )


def _published_commits_for_version(plugin_dir, version, published):
    """EVERY published commit whose manifest carried ``version``.

    All of them, not just the newest: a published history of v1/X -> v1/Y -> v1/X
    ends with an empty diff against the newest anchor, yet whoever installed while
    Y was current still holds different bytes under v1. Checking one snapshot would
    not establish the invariant this test claims.

    Anchors are found by walking the whole plugin directory, not just the manifest.
    A payload-only release changes the published tree without touching
    ``plugin.json``, so a manifest-only walk would never make it an anchor and a
    later rollback could match the *other* tree that shipped under the same version.
    This happened here: ``772e961`` changed two shipped review-chain files while the
    manifest stayed at ``0.1.0``.
    """
    manifest_rel = _manifest_rel(plugin_dir)
    relative = str(plugin_dir.relative_to(ROOT))
    commits = [c for c in _git("log", "--format=%H", published, "--", relative).splitlines() if c.strip()]
    return [c for c in commits if _version_at(c, manifest_rel) == version]


def test_every_plugin_version_maps_to_exactly_one_byte_tree():
    """One version key, one tree — for all time.

    A published version is a cache key on every machine that installed it, so the
    bytes it names can never change. That single invariant subsumes the whole
    family of failures found here: shipping edits without a bump, rolling a version
    back, deleting and re-adding a plugin at an old version, and doing any of those
    in the working tree rather than in a commit.

    Only *published* history constrains us. A version that does not yet appear on
    the base ref is new, so a branch is free to bump once and then keep editing —
    that is one release unit and squash-merges into a single commit.

    Known limitation, stated rather than papered over: two branches cut from the
    same base can independently pick the same new version, and each sees it as
    unpublished. Whichever merges second changes the bytes behind a key the first
    already published. A local test cannot see the other branch; closing that race
    needs a merge-time check (branch protection requiring the branch to be current,
    or a merge queue), which this repository does not have today.
    """
    plugin_dirs = _plugin_dirs()
    assert plugin_dirs, "no plugins discovered — the guard would pass vacuously"

    published = _published_ref()
    violations = {}
    for plugin_dir in plugin_dirs:
        relative = str(plugin_dir.relative_to(ROOT))
        manifest_rel = _manifest_rel(plugin_dir)

        # All THREE shippable states are checked, because they can disagree and each
        # can be what actually ships. A working-tree bump to v2 sitting on committed
        # payload edits still tagged v1 passes a HEAD-only check, then `git push`
        # carries the commits without the edit. Staging payload under v1 while the
        # v2 bump stays unstaged fools both HEAD and the working tree, yet
        # `git commit` records the index. Each is judged on its own version.
        states = {
            "HEAD": _version_at("HEAD", manifest_rel),
            "index": _version_in_index(plugin_dir),
            "working tree": _version_of(plugin_dir),
        }
        for label, version in states.items():
            if version == ABSENT:
                continue
            # This version was never published: nothing is cached under it anywhere.
            anchors = _published_commits_for_version(plugin_dir, version, published)
            changed = []
            for anchor in anchors:
                if label == "HEAD":
                    diff = _git("diff", "--name-only", anchor, "HEAD", "--", relative)
                elif label == "index":
                    diff = _git("diff", "--cached", "--name-only", anchor, "--", relative)
                else:
                    diff = _git("diff", "--name-only", anchor, "--", relative)
                changed += [f"{line} (vs published {anchor[:8]})" for line in diff.splitlines() if line.strip()]
            if label == "working tree" and anchors:
                changed += _uncommitted_payload_changes(plugin_dir)
            if changed:
                violations[f"{plugin_dir.name} [{label}]"] = (version, sorted(set(changed)))

    assert not violations, (
        "these bytes differ from what the same version already published — bump the "
        "version, or every existing install keeps the old bytes under this cache key:\n"
        + "\n".join(
            f"  {name}: version {version} was already published, but these differ:\n"
            + "\n".join(f"    {path}" for path in paths)
            for name, (version, paths) in sorted(violations.items())
        )
    )


def _local_tags():
    tags = [t for t in _git("tag", "--list").splitlines() if t.strip()]
    # No tags at all almost always means they were never fetched, and treating that
    # as "nothing is tagged" would turn this guard into a rubber stamp.
    assert tags, (
        "no git tags are present, so release tags cannot be verified. Fetch them "
        "(git fetch --tags) — an untagged clone must not pass this check silently."
    )
    return set(tags)


def _published_release_ref_pattern(plugin_source, published):
    """The tag pattern a plugin pinned *as published*, or None if it pinned nothing.

    Read from the published snapshot, never the working tree. Both halves of this
    check — which version is released, and which tag that release promised to
    publish — must come from the same commit, or the check contradicts itself:

      * a PR that REMOVES `RELEASE_REF` would silence the check for a release that
        still needs its tag (fail-open — the very PR that should be caught turns the
        guard off), and
      * a PR that ADDS `RELEASE_REF` would demand a tag for an already-published
        version that never promised one (false failure).

    Both were reproduced before this was written.

    Parsed rather than executed: it is a one-line template literal, and running
    plugin code from an arbitrary historical commit inside the test suite is not
    something to invite.

    ``plugin_source`` is the marketplace entry's own ``source`` (e.g. ``./plugins/codex``)
    rather than an assumed ``plugins/<name>`` layout: the marketplace decides where a
    plugin lives, and guessing would silently skip one that moved.
    """
    path = f"{plugin_source.rstrip('/')}/scripts/lib/version.mjs".lstrip("./")
    # "This plugin pins no ref" is a real answer, but — as with _version_at — it must
    # be established POSITIVELY. Treating any `git show` failure as absence would let a
    # corrupt object or a partial clone silently exempt a release from needing its tag,
    # which is the fail-open direction.
    listing = _git("ls-tree", "--name-only", published, "--", path)
    if not listing:
        return None
    source = _git("show", f"{published}:{path}")
    if not source:
        raise GitUnavailable(
            f"{published}:{path} is listed in the tree but read back empty; "
            "the release-tag guard cannot judge this plugin"
        )
    match = re.search(r"RELEASE_REF\s*=\s*`([^`]*)`", source)
    if not match:
        return None
    return match.group(1)


def _published_default_release_ref(plugin_source, published):
    """A release ref declared as a renderer DEFAULT rather than in version.mjs.

    codex has no version.mjs: its workflow template carries `{{RELEASE_REF}}` and the
    renderer substitutes `String(value ?? "v0.2.0")`. Keying discovery on version.mjs
    alone therefore exempted codex entirely, so a missing tag there was invisible.

    Only a literal default is read — a rendered workflow can override the ref at
    render time, and this guard is about what ships unconfigured.
    """
    path = f"{plugin_source.rstrip('/')}/scripts/lib/github-actions.mjs".lstrip("./")
    listing = _git("ls-tree", "--name-only", published, "--", path)
    if not listing:
        return None
    source = _git("show", f"{published}:{path}")
    if not source:
        raise GitUnavailable(
            f"{published}:{path} is listed in the tree but read back empty; "
            "the release-tag guard cannot judge this plugin"
        )
    match = re.search(r"""\?\?\s*["'`]([^"'`]+)["'`]\s*\)\s*\.trim\(\)""", source)
    return match.group(1) if match else None


def test_published_versions_have_the_release_tags_their_workflows_fetch():
    """A published version that pins a tag must have that tag, or CI cannot install it.

    The generated GitHub Actions workflows run
    ``git fetch --depth 1 origin "$..._RELEASE_REF"``. That ref went unpublished for
    every antigravity release before 0.1.3, so those workflows could never resolve
    it. Only versions already on the base ref are required to be tagged: a bump
    still in review is not released yet, and tagging happens after the merge.

    Two limits, stated rather than papered over:

    * Only the CURRENTLY published version is required to have its tag. Earlier
      antigravity releases (0.1.0-0.1.2) also declared a ref and were never tagged, so
      workflows rendered by them still cannot fetch. Fixing that means tagging release
      points after the fact, which manufactures a release history that did not exist;
      the gap is left visible instead.
    * A tag is matched by NAME against the local tag list. That does not prove the
      remote has it, nor that it points at the released bytes. Proving either needs
      network access, which does not belong in a unit suite — the merge-time story for
      that is a release step, not a test.
    """
    published = _published_ref()
    tags = _local_tags()
    missing = {}

    marketplace_ref = f"{published}:.claude-plugin/marketplace.json"
    published_marketplace = json.loads(_git("show", marketplace_ref))
    marketplace_version = published_marketplace["metadata"]["version"]
    if f"v{marketplace_version}" not in tags:
        missing["marketplace"] = f"v{marketplace_version}"

    # Iterate the PUBLISHED entries, not the working tree: a release that this PR
    # deletes still shipped, and its promised tag is still owed. Enumerating the
    # working tree would let a deletion skip the check.
    for entry in published_marketplace["plugins"]:
        name = entry["name"]
        # Resolve version.mjs from the entry's own `source`, not an assumed
        # plugins/<name> layout — the marketplace is what decides where a plugin lives.
        source = entry.get("source") or f"plugins/{name}"
        pattern = _published_release_ref_pattern(source, published)
        if pattern is not None:
            expected = pattern.replace("${PLUGIN_VERSION}", entry["version"])
        else:
            # Second mechanism: a renderer default, with no version.mjs (codex).
            expected = _published_default_release_ref(source, published)
        if not expected:
            continue
        if expected not in tags:
            missing[name] = expected

    assert not missing, (
        "these versions are published but carry no release tag, so the workflows that "
        "fetch them cannot resolve the ref — tag the release commit and push it:\n"
        + "\n".join(f"  {name}: expected tag {tag}" for name, tag in sorted(missing.items()))
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


def test_release_ref_discovery_covers_every_declaration_mechanism():
    """Two plugins declare a fetched ref two different ways; the guard must know both.

    antigravity exports ``RELEASE_REF`` from ``scripts/lib/version.mjs``. codex has no
    such file — its renderer defaults the ref in ``scripts/lib/github-actions.mjs``
    (``String(value ?? "v0.2.0")``) and the workflow fetches
    ``refs/tags/$CODEX_FOR_CLAUDE_RELEASE_REF``. Keying discovery on ``version.mjs``
    alone silently exempted codex, so a missing ``v0.2.0`` would not have been caught.

    This asserts the mechanisms themselves still exist, so that renaming or removing one
    fails here rather than quietly shrinking what the tag check covers.
    """
    published = _published_ref()
    mechanisms = {}
    for entry in json.loads(_git("show", f"{published}:.claude-plugin/marketplace.json"))["plugins"]:
        source = (entry.get("source") or f"plugins/{entry['name']}").rstrip("/").lstrip("./")
        if _published_release_ref_pattern(source, published):
            mechanisms[entry["name"]] = "version.mjs"
        elif _published_default_release_ref(source, published):
            mechanisms[entry["name"]] = "github-actions default"

    assert mechanisms.get("antigravity-for-claude") == "version.mjs", mechanisms
    assert mechanisms.get("codex") == "github-actions default", mechanisms
