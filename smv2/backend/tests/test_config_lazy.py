from __future__ import annotations

import app.config as config


def test_db_url_is_read_lazily(monkeypatch):
    monkeypatch.setenv("SMV2_DB_URL", "sqlite:////tmp/lazy-test-1.db")
    assert config.db_url() == "sqlite:////tmp/lazy-test-1.db"

    monkeypatch.setenv("SMV2_DB_URL", "sqlite:////tmp/lazy-test-2.db")
    assert config.db_url() == "sqlite:////tmp/lazy-test-2.db"


def test_max_upload_bytes_is_read_lazily(monkeypatch):
    assert config.max_upload_bytes() == 200 * 1024 * 1024

    monkeypatch.setenv("SMV2_MAX_UPLOAD_BYTES", "12345")
    assert config.max_upload_bytes() == 12345

    monkeypatch.setenv("SMV2_MAX_UPLOAD_BYTES", "not-a-number")
    assert config.max_upload_bytes() == 200 * 1024 * 1024


def test_pages_per_window_is_read_lazily(monkeypatch):
    assert config.pages_per_window() == 12

    monkeypatch.setenv("SMV2_PAGES_PER_WINDOW", "7")
    assert config.pages_per_window() == 7

    monkeypatch.setenv("SMV2_PAGES_PER_WINDOW", "not-a-number")
    assert config.pages_per_window() == 12
