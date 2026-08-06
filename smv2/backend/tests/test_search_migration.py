from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from app.db.engine import dispose_engine
from app.db.init import _alembic_config


def _rows(db_path: Path, query: str) -> list[sqlite3.Row]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(query).fetchall()
    finally:
        connection.close()


def _upgrade_to_0020(db_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SMV2_DB_URL", f"sqlite:///{db_path}")
    dispose_engine()
    command.upgrade(_alembic_config(), "0020_course_is_sample")


def test_search_migration_creates_core_table_and_fts_when_available(tmp_path, monkeypatch):
    db_path = tmp_path / "search-fts.db"
    _upgrade_to_0020(db_path, monkeypatch)

    command.upgrade(_alembic_config(), "0021_search_index")

    tables = {row["name"] for row in _rows(db_path, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "search_documents" in tables
    fts_available = bool(_rows(db_path, "SELECT sqlite_compileoption_used('ENABLE_FTS5') AS enabled")[0][0])
    if fts_available:
        assert "search_documents_fts" in tables

    command.downgrade(_alembic_config(), "0020_course_is_sample")
    tables_after = {
        row["name"] for row in _rows(db_path, "SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "search_documents" not in tables_after
    assert "search_documents_fts" not in tables_after


def test_search_migration_tolerates_missing_fts5_and_selects_like_backend(
    tmp_path, monkeypatch
):
    from app.db.engine import get_session
    from app.services import search_index

    db_path = tmp_path / "search-like.db"
    _upgrade_to_0020(db_path, monkeypatch)
    monkeypatch.setattr(search_index, "fts5_available", lambda session: False)

    command.upgrade(_alembic_config(), "0021_search_index")

    tables = {row["name"] for row in _rows(db_path, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "search_documents" in tables
    assert "search_documents_fts" not in tables
    session = get_session()
    try:
        assert search_index.ensure_search_backend(session) == "like"
    finally:
        session.close()
