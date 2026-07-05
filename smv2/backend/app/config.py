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


def max_upload_bytes() -> int:
    raw = os.environ.get("SMV2_MAX_UPLOAD_BYTES", str(200 * 1024 * 1024))
    try:
        return int(raw)
    except ValueError:
        return 200 * 1024 * 1024


def pages_per_window() -> int:
    raw = os.environ.get("SMV2_PAGES_PER_WINDOW", "12")
    try:
        return int(raw)
    except ValueError:
        return 12


def llm_provider() -> str:
    return os.environ.get("SMV2_LLM_PROVIDER", "anthropic")


def llm_model() -> str:
    return os.environ.get("SMV2_LLM_MODEL", "claude-sonnet-5")


def llm_max_concurrency() -> int:
    raw = os.environ.get("SMV2_LLM_MAX_CONCURRENCY", "2")
    try:
        return max(1, int(raw))
    except ValueError:
        return 2


def ollama_base_url() -> str:
    return os.environ.get("SMV2_OLLAMA_BASE_URL", "http://localhost:11434")


def course_spend_cap_usd() -> float | None:
    raw = os.environ.get("SMV2_COURSE_SPEND_CAP_USD")
    if raw is None or not raw.strip():
        return None
    try:
        return float(raw)
    except ValueError:
        return None
