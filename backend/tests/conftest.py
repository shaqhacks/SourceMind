"""Session-level test isolation for SourceMind.

This conftest ensures no test ever writes to the default ``data/sourcemind.db``
path.  It sets ``SOURCEMIND_DB_URL`` to a session-scoped tmp SQLite file before
any test runs.

Tests that already monkeypatch their own ``SOURCEMIND_DB_URL`` (e.g.
test_router_library, test_pipeline_service, test_review, test_db_base,
test_db_models) are **unaffected**: function-scoped ``monkeypatch.setenv`` calls
override os.environ for the duration of the test and restore to the session
value on teardown — never to the real default path.
"""

import os

import pytest

from SourceMind.backend.db import base


@pytest.fixture(scope="session", autouse=True)
def _default_db_isolation(tmp_path_factory):
    """Redirect the default DB URL to a tmp file for the whole test session.

    Any test that does NOT override ``SOURCEMIND_DB_URL`` itself will use this
    session-scoped SQLite file rather than ``sqlite:///data/sourcemind.db``.
    On session teardown all cached engines are disposed.
    """
    session_db = tmp_path_factory.mktemp("session_db") / "sourcemind_test.db"
    prev = os.environ.get("SOURCEMIND_DB_URL")
    os.environ["SOURCEMIND_DB_URL"] = f"sqlite:///{session_db}"
    yield
    # Restore original environment state.
    if prev is None:
        os.environ.pop("SOURCEMIND_DB_URL", None)
    else:
        os.environ["SOURCEMIND_DB_URL"] = prev
    base.reset_engine_cache()
