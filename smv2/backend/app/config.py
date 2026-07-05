"""Lazy configuration accessors.

Every value is read from os.environ at CALL time, never at import time.
Tests monkeypatch environment variables after `app.config` has already been
imported, so any module-level snapshot of os.environ would silently ignore
those overrides. Keep it that way.
"""

from __future__ import annotations

import os
from pathlib import Path

# backend/app/config.py -> backend/app -> backend -> smv2 (repo root for this app)
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def repo_root() -> Path:
    return _REPO_ROOT


def data_dir() -> Path:
    override = os.environ.get("SMV2_DATA_DIR")
    if override:
        return Path(override)
    return _REPO_ROOT / "data"


def db_url() -> str:
    override = os.environ.get("SMV2_DB_URL")
    if override:
        return override
    default_path = data_dir() / "smv2.db"
    return f"sqlite:///{default_path}"


def worker_enabled() -> bool:
    raw = os.environ.get("SMV2_WORKER_ENABLED", "1")
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def api_version() -> str:
    return "0.1.0"


def cors_origins() -> list[str]:
    raw = os.environ.get("SMV2_CORS_ORIGINS", "http://localhost:3000")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def backups_enabled() -> bool:
    raw = os.environ.get("SMV2_BACKUPS_ENABLED", "1")
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def backup_retention() -> int:
    raw = os.environ.get("SMV2_BACKUP_RETENTION", "7")
    try:
        return int(raw)
    except ValueError:
        return 7
