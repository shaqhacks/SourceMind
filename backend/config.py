"""Centralized environment-variable configuration for SourceMind's backend.

Every accessor re-reads ``os.environ`` on each call rather than snapshotting
values at import time. Tests rely on ``monkeypatch.setenv``/``delenv`` applied
*after* modules are imported (see backend/tests/conftest.py); snapshotting
here would silently break that isolation.
"""
from __future__ import annotations

import os

# ─── Database / storage ────────────────────────────────────────────────────

_DEFAULT_DB_URL = "sqlite:///data/sourcemind.db"
_DEFAULT_ASSETS_DIR = "data"


def db_url() -> str:
    """Database URL (env ``SOURCEMIND_DB_URL``)."""
    return os.environ.get("SOURCEMIND_DB_URL", _DEFAULT_DB_URL)


def assets_dir() -> str:
    """Base directory for extracted assets / pages.json (env ``SOURCEMIND_ASSETS_DIR``)."""
    return os.environ.get("SOURCEMIND_ASSETS_DIR", _DEFAULT_ASSETS_DIR)


# ─── CORS ───────────────────────────────────────────────────────────────────

_DEFAULT_CORS_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


def cors_origins() -> list[str]:
    """Allowed CORS origins: hardcoded localhost defaults plus any configured
    via ``SOURCEMIND_CORS_ORIGINS`` (comma-separated), deduplicated."""
    configured = [
        origin.strip()
        for origin in os.environ.get("SOURCEMIND_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    return [*_DEFAULT_CORS_ORIGINS, *[o for o in configured if o not in _DEFAULT_CORS_ORIGINS]]


# ─── LLM provider selection ─────────────────────────────────────────────────


def llm_provider() -> str:
    """Selected LLM provider name, lowercased (env ``SOURCEMIND_LLM_PROVIDER``, default 'claude')."""
    return os.environ.get("SOURCEMIND_LLM_PROVIDER", "claude").lower()


def llm_model(default: str) -> str:
    """Selected LLM model (env ``SOURCEMIND_LLM_MODEL``), falling back to *default*."""
    return os.environ.get("SOURCEMIND_LLM_MODEL", default)


# ─── Generic numeric env helpers ────────────────────────────────────────────


def env_float(name: str, default: float) -> float:
    """Parse env var *name* as a positive float, falling back to *default* on
    missing/invalid/non-positive values."""
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def env_int(name: str, default: int) -> int:
    """Parse env var *name* as a positive int, falling back to *default* on
    missing/invalid/non-positive values."""
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


# ─── LLM timeout ────────────────────────────────────────────────────────────

_DEFAULT_LLM_TIMEOUT = 120.0


def llm_timeout() -> float:
    """Per-call wall-clock budget in seconds (env ``SOURCEMIND_LLM_TIMEOUT``)."""
    return env_float("SOURCEMIND_LLM_TIMEOUT", _DEFAULT_LLM_TIMEOUT)


# ─── Upload / hardening limits (library.py) ────────────────────────────────

_DEFAULT_MAX_UPLOAD_MB = 50.0
_DEFAULT_MAX_TOTAL_MB = 200.0
_DEFAULT_MAX_TEXT_CHARS = 1_000_000
_DEFAULT_MAX_CONCURRENT_LLM = 4


def max_upload_bytes() -> int:
    return int(env_float("SOURCEMIND_MAX_UPLOAD_MB", _DEFAULT_MAX_UPLOAD_MB) * 1024 * 1024)


def max_total_upload_bytes() -> int:
    return int(env_float("SOURCEMIND_MAX_UPLOAD_TOTAL_MB", _DEFAULT_MAX_TOTAL_MB) * 1024 * 1024)


def max_text_chars() -> int:
    return env_int("SOURCEMIND_MAX_TEXT_CHARS", _DEFAULT_MAX_TEXT_CHARS)


def max_concurrent_llm() -> int:
    return env_int("SOURCEMIND_MAX_CONCURRENT_LLM", _DEFAULT_MAX_CONCURRENT_LLM)
