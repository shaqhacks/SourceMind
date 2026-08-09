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


def test_job_cancellation_migration_adds_nullable_cancel_requested_at(
    tmp_path, monkeypatch
):
    db_path = tmp_path / "job-cancellation.db"
    monkeypatch.setenv("SMV2_DB_URL", f"sqlite:///{db_path}")
    dispose_engine()
    command.upgrade(_alembic_config(), "0022_source_locators")

    command.upgrade(_alembic_config(), "0023_job_cancellation")

    columns = _rows(db_path, "PRAGMA table_info(jobs)")
    cancel_column = next(column for column in columns if column["name"] == "cancel_requested_at")
    assert cancel_column["notnull"] == 0

    command.downgrade(_alembic_config(), "0022_source_locators")

    columns_after_downgrade = _rows(db_path, "PRAGMA table_info(jobs)")
    assert "cancel_requested_at" not in {column["name"] for column in columns_after_downgrade}
