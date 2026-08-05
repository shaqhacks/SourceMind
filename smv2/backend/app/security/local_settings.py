from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

_CSRF_TOKEN = secrets.token_urlsafe(32)
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def csrf_token() -> str:
    return _CSRF_TOKEN


def require_local_settings_write(request: Request) -> None:
    _require_loopback(request)
    _require_same_origin(request)
    supplied = request.headers.get("x-smv2-csrf")
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


def _require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        raise HTTPException(status_code=403, detail="same-origin header is required")
    origin_host = urlsplit(origin).netloc
    host = request.headers.get("host", "")
    if origin_host != host:
        raise HTTPException(status_code=403, detail="origin must match request host")
