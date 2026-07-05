from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db.engine import dispose_engine
from app.db.init import init_db
from app.main import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SMV2_DB_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SMV2_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SMV2_WORKER_ENABLED", "0")
    monkeypatch.setenv("SMV2_BACKUPS_ENABLED", "0")
    dispose_engine()
    init_db()

    with TestClient(create_app()) as test_client:
        yield test_client

    dispose_engine()
