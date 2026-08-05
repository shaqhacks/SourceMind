from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app import config
from app.llm.probe import probe_provider

_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]+|[A-Za-z0-9_-]{20,})")
_last_check: dict[str, Any] | None = None


@dataclass
class LlmReadinessUnavailableError(Exception):
    detail: dict[str, Any]


def status_payload() -> dict[str, Any]:
    provider = config.llm_provider()
    model = config.llm_model()
    configured, category, remediation = _configured_state(provider)
    available = configured
    capabilities = _capabilities(provider, available)
    payload = {
        "provider": provider,
        "model": model,
        "configured": configured,
        "available": available,
        "capabilities": capabilities,
        "last_checked_at": _last_check["last_checked_at"] if _last_check else None,
        "failure_category": None if available else category,
        "remediation": None if available else remediation,
    }
    return payload


def check_payload() -> dict[str, Any]:
    global _last_check
    provider_name = config.llm_provider()
    model = config.llm_model()
    configured, category, remediation = _configured_state(provider_name)
    checked_at = datetime.now(timezone.utc).isoformat()
    if not configured:
        _last_check = {
            "provider": provider_name,
            "model": model,
            "configured": False,
            "available": False,
            "capabilities": _capabilities(provider_name, False),
            "last_checked_at": checked_at,
            "failure_category": category,
            "remediation": remediation,
        }
        return dict(_last_check)

    probe = probe_provider(provider_name)
    if not probe.available:
        _last_check = {
            "provider": provider_name,
            "model": model,
            "configured": True,
            "available": False,
            "capabilities": _capabilities(provider_name, False),
            "last_checked_at": checked_at,
            "failure_category": "provider_error",
            "remediation": _redact(probe.failure or "") or _remediation(provider_name),
        }
        return dict(_last_check)

    _last_check = {
        "provider": provider_name,
        "model": model,
        "configured": True,
        "available": True,
        "capabilities": _capabilities(provider_name, True),
        "last_checked_at": checked_at,
        "failure_category": None,
        "remediation": None,
    }
    return dict(_last_check)


def assert_ready_for_generation() -> None:
    payload = status_payload()
    if not payload["available"] or not payload["capabilities"]["completion"]:
        raise LlmReadinessUnavailableError(readiness_failure_detail(payload))


def readiness_failure_detail(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or status_payload()
    return {
        "message": "LLM provider is not ready",
        "failure_category": payload["failure_category"],
        "remediation": payload["remediation"],
    }


def settings_summary() -> dict[str, Any]:
    payload = status_payload()
    return {
        "provider": payload["provider"],
        "model": payload["model"],
        "configured": payload["configured"],
        "available": payload["available"],
        "capabilities": payload["capabilities"],
        "last_checked_at": payload["last_checked_at"],
        "failure_category": payload["failure_category"],
        "remediation": payload["remediation"],
    }


def _configured_state(provider: str) -> tuple[bool, str | None, str | None]:
    if provider == "anthropic":
        configured = bool(config.anthropic_api_key())
        return (
            configured,
            None if configured else "missing_credentials",
            None if configured else _remediation(provider),
        )
    if provider == "ollama":
        return True, None, None
    return False, "unknown_provider", f"Select a supported provider before using AI features."


def _capabilities(provider: str, available: bool) -> dict[str, bool]:
    if not available:
        return {"completion": False, "embeddings": False}
    return {"completion": True, "embeddings": provider == "ollama"}


def _remediation(provider: str) -> str:
    if provider == "anthropic":
        return "Add ANTHROPIC_API_KEY or save an Anthropic API key in local settings."
    if provider == "ollama":
        return "Start Ollama locally and confirm the configured base URL is reachable."
    return "Select anthropic or ollama in local settings."


def _redact(value: str) -> str:
    return _SECRET_RE.sub("[redacted]", value)
