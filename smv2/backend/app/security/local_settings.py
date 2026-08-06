from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from app import config

_CSRF_TOKEN = secrets.token_urlsafe(32)
CSRF_HEADER_NAME = "X-CSRF-Token"
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient", "testserver"}


def csrf_token() -> str:
    return _CSRF_TOKEN


def normalize_ollama_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "http"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("Ollama base URL must be an HTTP loopback origin")

    try:
        port = parsed.port or 11434
    except ValueError as exc:
        raise ValueError("Ollama base URL must use a valid port") from exc

    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname == "127.0.0.1":
        return f"http://127.0.0.1:{port}"
    if hostname == "::1":
        return f"http://[::1]:{port}"
    raise ValueError("Ollama base URL must use localhost, 127.0.0.1, or ::1")


def require_local_settings_write(request: Request) -> None:
    _require_loopback(request)
    _require_json(request)
    _require_trusted_loopback_origin(request)
    supplied = request.headers.get(CSRF_HEADER_NAME)
    if not supplied or not secrets.compare_digest(supplied, _CSRF_TOKEN):
        raise HTTPException(status_code=403, detail="CSRF token is missing or invalid")


def _require_loopback(request: Request) -> None:
    forwarded_for = request.headers.get("x-forwarded-for")
    candidates = [h.strip() for h in forwarded_for.split(",")] if forwarded_for else []
    if request.client is not None:
        candidates.append(request.client.host)
    if not candidates:
        raise HTTPException(status_code=403, detail="local settings writes require loopback access")
    if any(host not in _LOOPBACK_HOSTS for host in candidates):
        raise HTTPException(status_code=403, detail="local settings writes require loopback access")


def _require_json(request: Request) -> None:
    content_type = request.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(status_code=403, detail="settings writes require JSON content type")


def _require_trusted_loopback_origin(request: Request) -> None:
    host_tuple = _normalized_settings_origin(f"http://{request.headers.get('host', '')}")
    if host_tuple is None:
        raise HTTPException(status_code=403, detail="API host must be loopback")

    origin = request.headers.get("origin")
    if not origin:
        raise HTTPException(status_code=403, detail="trusted Origin header is required")

    origin_tuple = _normalized_settings_origin(origin)
    if origin_tuple is None:
        raise HTTPException(status_code=403, detail="Origin must be trusted loopback")

    trusted = {
        normalized
        for configured in config.cors_origins()
        if (normalized := _normalized_settings_origin(configured)) is not None
    }
    if origin_tuple not in trusted:
        raise HTTPException(status_code=403, detail="Origin is not configured for local settings")


def _normalized_settings_origin(value: str) -> tuple[str, str, int] | None:
    parsed = urlsplit(value)
    if parsed.scheme != "http" or not parsed.hostname:
        return None
    hostname = parsed.hostname.lower()
    if hostname not in _LOOPBACK_HOSTS:
        return None
    try:
        port = parsed.port or 80
    except ValueError:
        return None
    return (parsed.scheme, hostname, port)
