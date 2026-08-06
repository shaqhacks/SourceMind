from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

_MAX_RESPONSE_BYTES = 1024 * 1024
_MAX_TAGS = 100
_DISCOVERY_TIMEOUT = 5.0


class OllamaDiscoveryError(RuntimeError):
    def __init__(self, category: str, message: str, *, status_code: int):
        super().__init__(message)
        self.category = category
        self.status_code = status_code


async def discover_ollama_models(
    base_url: str, *, transport: httpx.AsyncBaseTransport | None = None
) -> list[str]:
    async with httpx.AsyncClient(
        base_url=base_url,
        follow_redirects=False,
        timeout=_DISCOVERY_TIMEOUT,
        transport=transport,
    ) as client:
        tags = await _request_json(client, "GET", "/api/tags")
        tag_names = _parse_tag_names(tags)
        semaphore = asyncio.Semaphore(4)

        async def is_completion_model(name: str) -> bool:
            async with semaphore:
                show = await _request_json(
                    client, "POST", "/api/show", json={"name": name}
                )
            capabilities = show.get("capabilities") if isinstance(show, dict) else None
            if not isinstance(capabilities, list) or not all(
                isinstance(item, str) for item in capabilities
            ):
                raise OllamaDiscoveryError(
                    "ollama_invalid_response",
                    "Ollama returned an invalid model metadata response.",
                    status_code=502,
                )
            return "completion" in {item.lower() for item in capabilities}

        checks = await asyncio.gather(
            *(is_completion_model(name) for name in tag_names)
        )

    models = {
        name.lower()
        for name, compatible in zip(tag_names, checks, strict=True)
        if compatible
    }
    if not models:
        raise OllamaDiscoveryError(
            "ollama_no_completion_models",
            "Ollama did not report any completion-capable models.",
            status_code=503,
        )
    return sorted(models)


async def _request_json(
    client: httpx.AsyncClient, method: str, path: str, **kwargs: Any
) -> Any:
    try:
        response = await client.request(method, path, **kwargs)
    except httpx.TimeoutException as exc:
        raise OllamaDiscoveryError(
            "ollama_timeout",
            "Ollama did not respond before the request timed out.",
            status_code=503,
        ) from exc
    except httpx.ConnectError as exc:
        raise OllamaDiscoveryError(
            "ollama_unreachable",
            "Ollama could not be reached.",
            status_code=503,
        ) from exc
    except httpx.HTTPError as exc:
        raise OllamaDiscoveryError(
            "ollama_unreachable",
            "Ollama could not be reached.",
            status_code=503,
        ) from exc

    if response.is_redirect:
        raise OllamaDiscoveryError(
            "ollama_invalid_response",
            "Ollama returned an unsupported redirect response.",
            status_code=502,
        )
    if response.status_code >= 400:
        raise OllamaDiscoveryError(
            "ollama_unreachable",
            "Ollama returned an unsuccessful response.",
            status_code=503,
        )

    raw = await _read_limited(response)
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise OllamaDiscoveryError(
            "ollama_invalid_response",
            "Ollama returned an invalid JSON response.",
            status_code=502,
        ) from exc


async def _read_limited(response: httpx.Response) -> bytes:
    total = 0
    chunks: list[bytes] = []
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > _MAX_RESPONSE_BYTES:
            raise OllamaDiscoveryError(
                "ollama_invalid_response",
                "Ollama returned a response that was too large.",
                status_code=502,
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_tag_names(payload: Any) -> list[str]:
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise OllamaDiscoveryError(
            "ollama_invalid_response",
            "Ollama returned an invalid models response.",
            status_code=502,
        )
    if len(models) > _MAX_TAGS:
        raise OllamaDiscoveryError(
            "ollama_invalid_response",
            "Ollama returned too many models.",
            status_code=502,
        )
    if not models:
        raise OllamaDiscoveryError(
            "ollama_no_models",
            "Ollama did not report any models.",
            status_code=503,
        )

    names: list[str] = []
    for item in models:
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name.strip():
            raise OllamaDiscoveryError(
                "ollama_invalid_response",
                "Ollama returned an invalid model entry.",
                status_code=502,
            )
        names.append(name.strip())
    return names
