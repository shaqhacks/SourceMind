from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import anthropic
import httpx

from app.config import anthropic_api_key, embed_model, llm_model, ollama_base_url
from app.security.local_settings import normalize_ollama_base_url

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
        base_url = normalize_ollama_base_url(ollama_base_url())
        with httpx.Client(
            base_url=base_url,
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
    payload = _show_model_payload(client, model_name)
    capabilities = payload.get("capabilities") if isinstance(payload, dict) else None
    if not isinstance(capabilities, list) or not all(
        isinstance(item, str) for item in capabilities
    ):
        raise RuntimeError("Ollama returned an invalid model metadata response.")
    return capability in {item.lower() for item in capabilities}


def _show_model_payload(client: httpx.Client, model_name: str) -> Any:
    with client.stream("POST", "/api/show", json={"name": model_name}) as response:
        if response.is_redirect:
            raise RuntimeError("Ollama returned an unsupported redirect response.")
        if response.status_code == 404:
            return {"capabilities": []}
        response.raise_for_status()
        raw = _read_limited(response)
    try:
        return json.loads(raw)
    except ValueError:
        raise RuntimeError("Ollama returned an invalid JSON response.") from None


def _read_limited(response: httpx.Response) -> bytes:
    total = 0
    chunks: list[bytes] = []
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > _MAX_RESPONSE_BYTES:
            raise RuntimeError("Ollama returned a response that was too large.")
        chunks.append(chunk)
    return b"".join(chunks)
