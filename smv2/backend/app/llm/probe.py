from __future__ import annotations

from dataclasses import dataclass

import anthropic
import httpx

from app.config import anthropic_api_key, ollama_base_url

_OLLAMA_PROBE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ProbeResult:
    available: bool
    failure: str | None = None


def probe_provider(provider: str) -> ProbeResult:
    if provider == "anthropic":
        return _probe_anthropic()
    if provider == "ollama":
        return _probe_ollama()
    return ProbeResult(False, f"unknown LLM provider: {provider}")


def _probe_anthropic() -> ProbeResult:
    try:
        client = anthropic.Anthropic(api_key=anthropic_api_key(), max_retries=0)
        client.models.list()
    except Exception as exc:
        return ProbeResult(False, str(exc))
    return ProbeResult(True)


def _probe_ollama() -> ProbeResult:
    try:
        response = httpx.get(
            f"{ollama_base_url().rstrip('/')}/api/version",
            timeout=_OLLAMA_PROBE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except Exception as exc:
        return ProbeResult(False, str(exc))
    return ProbeResult(True)
