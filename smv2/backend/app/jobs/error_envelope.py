from __future__ import annotations

import json
from typing import Any

PREFIX = "SMV2_JOB_ERROR:"


def encode_job_error(message: str, detail: dict[str, Any]) -> str:
    payload = {"message": message, "detail": detail}
    return f"{PREFIX}{json.dumps(payload, separators=(',', ':'), sort_keys=True)}"


def decode_job_error(raw: str | None) -> tuple[str | None, dict[str, Any] | None]:
    if raw is None:
        return None, None
    if not raw.startswith(PREFIX):
        return raw, None
    try:
        payload = json.loads(raw[len(PREFIX):])
    except json.JSONDecodeError:
        return raw, None
    if not isinstance(payload, dict):
        return raw, None
    message = payload.get("message")
    detail = payload.get("detail")
    if not isinstance(message, str) or not isinstance(detail, dict):
        return raw, None
    return message, detail
