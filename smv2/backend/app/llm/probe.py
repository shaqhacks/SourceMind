from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import anthropic
import httpx

from app.config import anthropic_api_key, embed_model, llm_model, ollama_base_url

_OLLAMA_PROBE_TIMEOUT_SECONDS = 5.0
_OLLAMA_PROBE_TIMEOUT = httpx.Timeout(_OLLAMA_PROBE_TIMEOUT_SECONDS, connect=1.0, read=5.0)
_MAX_RESPONSE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class ProbeResult:
    available: bool
    failure: str | None = None
    completion: bool = False
    embeddings: bool = False
    failure_category: str | None = None


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
    except (anthropic.AnthropicError, httpx.HTTPError, RuntimeError, TypeError, ValueError) as exc:
        return ProbeResult(False, str(exc))
    return ProbeResult(True, completion=True)


def _probe_ollama() -> ProbeResult:
    try:
        with httpx.Client(
            base_url=ollama_base_url().rstrip("/"),
            follow_redirects=False,
            timeout=_OLLAMA_PROBE_TIMEOUT,
        ) as client:
            completion = _model_has_capability(client, llm_model(), "completion")
            embeddings = _model_has_capability(client, embed_model(), "embedding")
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        return ProbeResult(
            False,
            str(exc),
            failure_category="unreachable",
        )
    if not completion:
        return ProbeResult(
            False,
            "Install the configured Ollama completion model before using AI features.",
            completion=False,
            embeddings=embeddings,
            failure_category="ollama_model_unavailable",
        )
    if not embeddings:
        return ProbeResult(
            True,
            "Install the configured Ollama embedding model to enable semantic retrieval.",
            completion=True,
            embeddings=False,
            failure_category="ollama_embed_model_unavailable",
        )
    return ProbeResult(True, completion=True, embeddings=True)


def _model_has_capability(client: httpx.Client, model_name: str, capability: str) -> bool:
    response = client.post("/api/show", json={"name": model_name})
    if response.is_redirect:
        raise RuntimeError("Ollama returned an unsupported redirect response.")
    if response.status_code == 404:
        return False
    response.raise_for_status()
    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise RuntimeError("Ollama returned a response that was too large.")
    payload: Any = response.json()
    capabilities = payload.get("capabilities") if isinstance(payload, dict) else None
    if not isinstance(capabilities, list) or not all(
        isinstance(item, str) for item in capabilities
    ):
        raise RuntimeError("Ollama returned an invalid model metadata response.")
    return capability in {item.lower() for item in capabilities}
