"""Shared pytest configuration for the external-models-for-claude test suite.

The tests build job/state fixtures with explicit (often absent) ``sessionId`` and
then invoke the companion CLIs, which inherit ``os.environ``. When the suite runs
*inside* a live Codex/Claude session, that ambient environment exports
``CODEX_COMPANION_SESSION_ID`` (and may export the ``CODEX_COMPANION_APP_SERVER_*``
broker vars). The companion then scopes ``status``/job listings to that ambient
session id via ``filterJobsForCurrentSession`` and drops the unscoped test jobs,
which surfaces as ``StopIteration`` (e.g. the status-liveness tests) — a
test-environment artifact, not a product bug.

The same live-session ambient environment also exports ``CLAUDE_PLUGIN_DATA``,
which every plugin resolves its on-disk state root from. A test that forgets to
override it inherits the HOST's real plugin-data directory instead of its own
tmp_path fixture, so state-root-dependent assertions run against live host state
instead of the isolated fixture -- confirmed by running the suite inside a live
session: 17 tests fail on a TypeError/StopIteration class of error that vanishes
the moment the ambient var is cleared.

Strip these ambient variables once at collection time so the suite is hermetic
regardless of the shell it runs in. Tests that need a session id, broker
endpoint, or a specific plugin-data root set it explicitly in their own ``env``
mapping.
"""

import os

# Companion/host env vars that leak from a live host session and would otherwise
# scope job/status/runtime/state-root resolution to the host instead of the
# per-test fixture.
_LEAKING_COMPANION_ENV_VARS = (
    "CODEX_COMPANION_SESSION_ID",
    "CODEX_COMPANION_APP_SERVER_ENDPOINT",
    "CODEX_COMPANION_APP_SERVER_LOG_FILE",
    "CODEX_COMPANION_APP_SERVER_PID_FILE",
    "CLAUDE_PLUGIN_DATA",
)


def _scrub_ambient_companion_env():
    for name in _LEAKING_COMPANION_ENV_VARS:
        os.environ.pop(name, None)


# Run at import time (pytest imports conftest before collecting tests) so every
# subsequent ``os.environ.copy()`` in the helpers starts from a clean baseline.
_scrub_ambient_companion_env()
