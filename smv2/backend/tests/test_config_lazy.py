from __future__ import annotations

import app.config as config


def test_db_url_is_read_lazily(monkeypatch):
    monkeypatch.setenv("SMV2_DB_URL", "sqlite:////tmp/lazy-test-1.db")
    assert config.db_url() == "sqlite:////tmp/lazy-test-1.db"

    monkeypatch.setenv("SMV2_DB_URL", "sqlite:////tmp/lazy-test-2.db")
    assert config.db_url() == "sqlite:////tmp/lazy-test-2.db"
