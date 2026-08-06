from __future__ import annotations

import json

import httpx
import pytest

from app.services.ollama_discovery_service import (
    OllamaDiscoveryError,
    discover_ollama_models,
)


pytestmark = pytest.mark.anyio


def _json_response(payload: object) -> httpx.Response:
    return httpx.Response(
        200,
        content=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


async def test_service_returns_sorted_deduplicated_completion_models_only():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return _json_response(
                {
                    "models": [
                        {"name": "llama3.2:latest"},
                        {"name": "embedding-only:latest"},
                        {"name": "GEMMA3:4B"},
                        {"name": "gemma3:4b"},
                    ]
                }
            )
        if request.url.path == "/api/show":
            name = json.loads(request.content.decode("utf-8"))["name"]
            capabilities = {
                "llama3.2:latest": ["completion", "tools"],
                "embedding-only:latest": ["embedding"],
                "GEMMA3:4B": ["completion"],
                "gemma3:4b": ["completion"],
            }[name]
            return _json_response({"capabilities": capabilities})
        raise AssertionError(f"unexpected request path {request.url.path}")

    models = await discover_ollama_models(
        "http://127.0.0.1:11434",
        transport=httpx.MockTransport(handler),
    )

    assert models == ["gemma3:4b", "llama3.2:latest"]


@pytest.mark.parametrize(
    ("response", "category"),
    [
        (
            httpx.Response(302, headers={"location": "/upstream-secret"}),
            "ollama_invalid_response",
        ),
        (httpx.Response(200, content=b"{upstream-secret"), "ollama_invalid_response"),
        (
            httpx.Response(200, content=b"x" * (1024 * 1024 + 1)),
            "ollama_invalid_response",
        ),
        (
            _json_response(
                {"models": [{"name": f"model-{index}"} for index in range(101)]}
            ),
            "ollama_invalid_response",
        ),
        (
            _json_response({"models": [{"model": "llama3.2:latest"}]}),
            "ollama_invalid_response",
        ),
        (_json_response({"models": []}), "ollama_no_models"),
    ],
)
async def test_service_rejects_invalid_tag_responses_without_leaking_raw_upstream_data(
    response: httpx.Response,
    category: str,
):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return response

    with pytest.raises(OllamaDiscoveryError) as exc_info:
        await discover_ollama_models(
            "http://127.0.0.1:11434",
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.category == category
    assert "upstream-secret" not in str(exc_info.value)
    assert "/api/" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("exception", "category"),
    [
        (httpx.ConnectError("upstream-secret /api/tags"), "ollama_unreachable"),
        (httpx.ReadTimeout("upstream-secret /api/tags"), "ollama_timeout"),
    ],
)
async def test_service_maps_network_failures_to_safe_categories(
    exception: httpx.HTTPError,
    category: str,
):
    async def handler(request: httpx.Request) -> httpx.Response:
        raise exception

    with pytest.raises(OllamaDiscoveryError) as exc_info:
        await discover_ollama_models(
            "http://127.0.0.1:11434",
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.category == category
    assert "upstream-secret" not in str(exc_info.value)
    assert "/api/" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("show_response", "category"),
    [
        (
            _json_response({"capabilities": ["embedding"]}),
            "ollama_no_completion_models",
        ),
        (_json_response({"capabilities": "completion"}), "ollama_invalid_response"),
        (
            httpx.Response(200, content=b"x" * (1024 * 1024 + 1)),
            "ollama_invalid_response",
        ),
    ],
)
async def test_service_rejects_incompatible_or_invalid_show_responses(
    show_response: httpx.Response,
    category: str,
):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return _json_response({"models": [{"name": "llama3.2:latest"}]})
        if request.url.path == "/api/show":
            return show_response
        raise AssertionError(f"unexpected request path {request.url.path}")

    with pytest.raises(OllamaDiscoveryError) as exc_info:
        await discover_ollama_models(
            "http://127.0.0.1:11434",
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.category == category
    assert "upstream-secret" not in str(exc_info.value)
    assert "/api/" not in str(exc_info.value)
