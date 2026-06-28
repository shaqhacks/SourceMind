import os
from SourceMind.backend.db import base


def test_init_db_creates_sqlite(tmp_path, monkeypatch):
    db_file = tmp_path / "t.db"
    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{db_file}")
    eng = base.make_engine()
    assert eng.url.database.endswith("t.db")


def test_get_session_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{tmp_path / 't.db'}")
    base.init_db(base.make_engine())
    with base.get_session() as s:
        assert s.execute(__import__("sqlalchemy").text("select 1")).scalar() == 1
