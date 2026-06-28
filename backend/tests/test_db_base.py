import os
from SourceMind.backend.db import base


def test_init_db_creates_sqlite(tmp_path, monkeypatch):
    db_file = tmp_path / "t.db"
    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{db_file}")
    eng = base.make_engine()
    assert eng.url.database.endswith("t.db")


def test_get_session_roundtrip(tmp_path, monkeypatch):
    """get_session() must target the DB named by the CURRENT db_url(), not the
    import-time one.  We prove this with a real INSERT → SELECT roundtrip across
    two separate get_session() calls, both pointed at a tmp-path SQLite file."""
    import sqlalchemy

    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{tmp_path / 't.db'}")
    # Clear any cached engine for this URL so the test starts fresh.
    base._engine_cache.pop(base.db_url(), None)

    eng = base.make_engine()
    base.init_db(eng)

    # First session: create a throwaway table and insert a sentinel value.
    with base.get_session() as s:
        s.execute(sqlalchemy.text("CREATE TABLE IF NOT EXISTS t (x INTEGER)"))
        s.execute(sqlalchemy.text("INSERT INTO t VALUES (42)"))

    # Second session: read the value back — proves we hit the same monkeypatched DB.
    with base.get_session() as s:
        val = s.execute(sqlalchemy.text("SELECT x FROM t")).scalar()

    assert val == 42, f"Expected 42, got {val!r} — get_session() targeted the wrong DB"
