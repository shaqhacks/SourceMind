from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from app.db.engine import dispose_engine
from app.db.init import _alembic_config


_NOW = "2026-08-05 12:00:00"


def _rows(db_path: Path, query: str) -> list[sqlite3.Row]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(query).fetchall()
    finally:
        connection.close()


def test_course_is_sample_upgrade_defaults_false_and_downgrade_preserves_rows(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "course-is-sample.db"
    monkeypatch.setenv("SMV2_DB_URL", f"sqlite:///{db_path}")
    dispose_engine()
    command.upgrade(_alembic_config(), "0019_diagnostic_validation")

    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            "INSERT INTO courses (id, title, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("existing-course", "Existing course", "ready", _NOW, _NOW),
        )
        connection.commit()
    finally:
        connection.close()

    command.upgrade(_alembic_config(), "0020_course_is_sample")

    columns = _rows(db_path, "PRAGMA table_info(courses)")
    sample_column = next(column for column in columns if column["name"] == "is_sample")
    assert sample_column["notnull"] == 1
    assert sample_column["dflt_value"] in {"0", "false", "FALSE"}
    assert _rows(db_path, "SELECT is_sample FROM courses WHERE id = 'existing-course'")[0][0] == 0

    command.downgrade(_alembic_config(), "0019_diagnostic_validation")

    columns_after_downgrade = _rows(db_path, "PRAGMA table_info(courses)")
    assert "is_sample" not in {column["name"] for column in columns_after_downgrade}
    row = _rows(db_path, "SELECT id, title, status FROM courses WHERE id = 'existing-course'")[0]
    assert dict(row) == {
        "id": "existing-course",
        "title": "Existing course",
        "status": "ready",
    }
