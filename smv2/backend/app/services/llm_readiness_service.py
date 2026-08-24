from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from app import config
from app.llm.probe import probe_provider

_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_-]+|[A-Za-z0-9_-]{20,})")
_CACHE_FRESH_SECONDS = 30.0
_last_check: dict[str, Any] | None = None


@dataclass
class LlmReadinessUnavailableError(Exception):
    detail: dict[str, Any]


def status_payload() -> dict[str, Any]:
    provider = config.llm_provider()
    model = config.llm_model()
    identity = _config_identity(provider, model)
    if _last_check is not None and _last_check.get("identity") == identity:
        return _public_payload(_last_check)
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
    identity = _config_identity(provider_name, model)
    configured, category, remediation = _configured_state(provider_name)
    checked_at = datetime.now(UTC).isoformat()
    checked_monotonic = time.monotonic()
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
            "identity": identity,
            "checked_monotonic": checked_monotonic,
        }
        return _public_payload(_last_check)

    probe = probe_provider(provider_name)
    if not probe.available or not probe.completion:
        _last_check = {
            "provider": provider_name,
            "model": model,
            "configured": True,
            "available": False,
            "capabilities": _capabilities_from_probe(probe),
            "last_checked_at": checked_at,
            "failure_category": probe.failure_category or "unreachable",
            "remediation": _redact(probe.failure or "") or _remediation(provider_name),
            "identity": identity,
            "checked_monotonic": checked_monotonic,
        }
        return _public_payload(_last_check)

    _last_check = {
        "provider": provider_name,
        "model": model,
        "configured": True,
        "available": True,
        "capabilities": _capabilities_from_probe(probe),
        "last_checked_at": checked_at,
        "failure_category": probe.failure_category,
        "remediation": _redact(probe.failure or "") if probe.failure_category else None,
        "identity": identity,
        "checked_monotonic": checked_monotonic,
    }
    return _public_payload(_last_check)


def assert_ready_for_generation() -> None:
    provider = config.llm_provider()
    model = config.llm_model()
    identity = _config_identity(provider, model)
    if provider == "ollama" and (
        _last_check is None or _last_check.get("identity") != identity or not _cache_is_fresh(_last_check)
    ):
        payload = check_payload()
    else:
        payload = (
            _public_payload(_last_check)
            if _last_check is not None and _last_check.get("identity") == identity
            else status_payload()
        )
    if not payload["available"] or not payload["capabilities"]["completion"]:
        raise LlmReadinessUnavailableError(readiness_failure_detail(payload))


def assert_curriculum_ready() -> None:
    """Gate skill-map (curriculum) generation on the *curriculum* provider's
    credentials — that path may use a different provider (e.g. Gemini) than
    everything else, so the generic assert_ready_for_generation() (which
    checks the default provider) is not sufficient."""
    provider = config.curriculum_provider()
    configured, category, remediation = _configured_state(provider)
    if not configured:
        raise LlmReadinessUnavailableError(
            readiness_failure_detail(
                {"failure_category": category, "remediation": remediation}
            )
        )


def readiness_failure_detail(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or status_payload()
    return {
        "code": "llm_readiness_unavailable",
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


def _public_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"identity", "checked_monotonic"}
    }


def _config_identity(provider: str, model: str) -> str:
    if provider in ("anthropic", "deepseek", "gemini"):
        if provider == "anthropic":
            credential = config.anthropic_api_key() or ""
        elif provider == "deepseek":
            credential = config.deepseek_api_key() or ""
        else:
            credential = config.gemini_api_key() or ""
        material = f"{provider}\0{model}\0{_digest(credential)}"
    elif provider == "ollama":
        material = f"{provider}\0{model}\0{config.embed_model()}\0{config.ollama_base_url()}"
    else:
        material = f"{provider}\0{model}"
    return sha256(material.encode("utf-8")).hexdigest()


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _configured_state(provider: str) -> tuple[bool, str | None, str | None]:
    if provider == "anthropic":
        configured = bool(config.anthropic_api_key())
        return (
            configured,
            None if configured else "missing_credentials",
            None if configured else _remediation(provider),
        )
    if provider == "deepseek":
        configured = bool(config.deepseek_api_key())
        return (
            configured,
            None if configured else "missing_credentials",
            None if configured else _remediation(provider),
        )
    if provider == "gemini":
        configured = bool(config.gemini_api_key())
        return (
            configured,
            None if configured else "missing_credentials",
            None if configured else _remediation(provider),
        )
    if provider == "ollama":
        configured = config.ollama_base_url_configured()
        return (
            configured,
            None if configured else "missing_credentials",
            None if configured else _remediation(provider),
        )
    return False, "unknown_provider", "Select a supported provider before using AI features."


def _capabilities(provider: str, available: bool) -> dict[str, bool]:
    if not available:
        return {"completion": False, "embeddings": False}
    return {"completion": True, "embeddings": provider in {"ollama", "gemini"}}


def _capabilities_from_probe(probe) -> dict[str, bool]:
    return {"completion": probe.completion, "embeddings": probe.embeddings}


def _cache_is_fresh(payload: dict[str, Any]) -> bool:
    checked_monotonic = payload.get("checked_monotonic")
    if not isinstance(checked_monotonic, (int, float)):
        return False
    return time.monotonic() - checked_monotonic < _CACHE_FRESH_SECONDS


def _remediation(provider: str) -> str:
    if provider == "anthropic":
        return "Add ANTHROPIC_API_KEY or save an Anthropic API key in local settings."
    if provider == "deepseek":
        return "Add DEEPSEEK_API_KEY or save a DeepSeek API key in local settings."
    if provider == "gemini":
        return "Add GEMINI_API_KEY or save a Gemini API key in local settings."
    if provider == "ollama":
        return "Start Ollama locally and confirm the configured base URL is reachable."
    return "Select anthropic or ollama in local settings."


def _redact(value: str) -> str:
    return _SECRET_RE.sub("[redacted]", value)
