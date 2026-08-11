from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest

from app.llm import ollama_discovery_service
from app.llm.ollama_discovery_service import (
    OllamaDiscoveryError,
    discover_ollama_models,
)


pytestmark = pytest.mark.anyio


class StreamingBody(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


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

    assert models == ["GEMMA3:4B", "llama3.2:latest"]


async def test_service_preserves_exact_model_identifier_when_deduplicating_case_insensitively():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return _json_response(
                {
                    "models": [
                        {"name": "Beta:Latest"},
                        {"name": "alpha:latest"},
                        {"name": "BETA:latest"},
                    ]
                }
            )
        if request.url.path == "/api/show":
            return _json_response({"capabilities": ["completion"]})
        raise AssertionError(f"unexpected request path {request.url.path}")

    models = await discover_ollama_models(
        "http://127.0.0.1:11434",
        transport=httpx.MockTransport(handler),
    )

    assert models == ["alpha:latest", "Beta:Latest"]


async def test_service_limits_concurrent_model_metadata_requests_to_four():
    in_flight = 0
    max_in_flight = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, max_in_flight
        if request.url.path == "/api/tags":
            return _json_response(
                {"models": [{"name": f"model-{index}"} for index in range(9)]}
            )
        if request.url.path == "/api/show":
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            return _json_response({"capabilities": ["completion"]})
        raise AssertionError(f"unexpected request path {request.url.path}")

    models = await discover_ollama_models(
        "http://127.0.0.1:11434",
        transport=httpx.MockTransport(handler),
    )

    assert len(models) == 9
    assert max_in_flight == 4


async def test_service_enforces_response_cap_while_streaming_before_full_body_buffer():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=StreamingBody([b"x" * (512 * 1024), b"upstream-secret" * 50000]),
        )

    with pytest.raises(OllamaDiscoveryError) as exc_info:
        await discover_ollama_models(
            "http://127.0.0.1:11434",
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.category == "ollama_invalid_response"
    assert exc_info.value.__cause__ is None
    assert "upstream-secret" not in str(exc_info.value)


async def test_service_uses_explicit_httpx_timeout_configuration(monkeypatch):
    captured_timeout: httpx.Timeout | None = None

    class SpyAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            nonlocal captured_timeout
            captured_timeout = kwargs.get("timeout")
            super().__init__(*args, **kwargs)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return _json_response({"models": [{"name": "llama3.2:latest"}]})
        if request.url.path == "/api/show":
            return _json_response({"capabilities": ["completion"]})
        raise AssertionError(f"unexpected request path {request.url.path}")

    monkeypatch.setattr(ollama_discovery_service.httpx, "AsyncClient", SpyAsyncClient)

    await discover_ollama_models(
        "http://127.0.0.1:11434",
        transport=httpx.MockTransport(handler),
    )

    assert isinstance(captured_timeout, httpx.Timeout)
    assert captured_timeout.connect == 1.0
    assert captured_timeout.read == 5.0


async def test_service_total_discovery_timeout_maps_to_safe_timeout(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.01)
        return _json_response({"models": [{"name": "llama3.2:latest"}]})

    monkeypatch.setattr(ollama_discovery_service, "_TOTAL_DISCOVERY_TIMEOUT", 0.001)

    with pytest.raises(OllamaDiscoveryError) as exc_info:
        await discover_ollama_models(
            "http://127.0.0.1:11434",
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.category == "ollama_timeout"
    assert exc_info.value.__cause__ is None


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
    assert exc_info.value.__cause__ is None
    assert "upstream-secret" not in str(exc_info.value)
    assert "/api/" not in str(exc_info.value)


async def test_service_suppresses_httpx_exception_cause_with_raw_request_url():
    request = httpx.Request("GET", "http://127.0.0.1:11434/api/tags?token=upstream-secret")

    async def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect failed", request=request)

    with pytest.raises(OllamaDiscoveryError) as exc_info:
        await discover_ollama_models(
            "http://127.0.0.1:11434",
            transport=httpx.MockTransport(handler),
        )

    assert exc_info.value.category == "ollama_unreachable"
    assert exc_info.value.__cause__ is None
    assert "upstream-secret" not in repr(exc_info.value)


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
