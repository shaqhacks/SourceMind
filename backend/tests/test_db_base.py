import os
import pytest
from SourceMind.backend.db import base


@pytest.fixture(autouse=True)
def _cleanup_engine_cache():
    """Dispose all cached engines after each test to prevent ResourceWarning."""
    yield
    base.reset_engine_cache()


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

    # First session: create a throwaway table and insert a sentinel value.
    with base.get_session() as s:
        s.execute(sqlalchemy.text("CREATE TABLE IF NOT EXISTS t (x INTEGER)"))
        s.execute(sqlalchemy.text("INSERT INTO t VALUES (42)"))

    # Second session: read the value back — proves we hit the same monkeypatched DB.
    with base.get_session() as s:
        val = s.execute(sqlalchemy.text("SELECT x FROM t")).scalar()

    assert val == 42, f"Expected 42, got {val!r} — get_session() targeted the wrong DB"


def test_init_db_upgrades_pre_alembic_database(tmp_path, monkeypatch):
    """A database with tables but no ``alembic_version`` row (i.e. one created
    by ``create_all()`` before Alembic was introduced) must be detected,
    stamped at the baseline revision, then upgraded to head.

    Verifies the upgrade actually ran: the dead ``chapters.assets`` column is
    gone at the DB level, pre-existing row data survived the SQLite
    batch-table-recreate, and ``courses.created_at`` is now DateTime-backed
    (its server_default populates a freshly inserted row).
    """
    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config as AlembicConfig

    db_file = tmp_path / "legacy.db"
    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{db_file}")

    # Build a DB at exactly the baseline schema (revision 0001) using the real
    # baseline migration, then drop alembic_version to simulate a database
    # that predates Alembic (schema present, no version tracking).
    legacy_engine = sa.create_engine(f"sqlite:///{db_file}")
    cfg = AlembicConfig(str(base._ALEMBIC_INI))
    cfg.set_main_option("script_location", str(base._MIGRATIONS_DIR))
    with legacy_engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0001")
    with legacy_engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO courses (id, title) VALUES ('c1', 'Legacy Course')"))
        conn.execute(sa.text(
            "INSERT INTO chapters (id, course_id, title, assets) VALUES (1, 'c1', 'Chapter One', '[]')"
        ))
        conn.execute(sa.text("DROP TABLE alembic_version"))
    legacy_engine.dispose()

    base.init_db()  # must detect the pre-Alembic schema, stamp baseline, then upgrade to head

    from SourceMind.backend.db import models

    with base.get_session() as session:
        chapter = session.query(models.Chapter).filter_by(course_id="c1").first()
        assert chapter is not None and chapter.title == "Chapter One", (
            "existing row data must survive the SQLite batch-table-recreate"
        )
        session.add(models.Course(id="c2", title="New Course"))

    with base.get_session() as session:
        new_course = session.get(models.Course, "c2")
        assert new_course.created_at is not None, (
            "created_at should be DateTime-backed with an active server_default post-upgrade"
        )

    inspector = sa.inspect(base._engine_cache[base.db_url()][0])
    assert "assets" not in {c["name"] for c in inspector.get_columns("chapters")}
    assert "alembic_version" in inspector.get_table_names()
