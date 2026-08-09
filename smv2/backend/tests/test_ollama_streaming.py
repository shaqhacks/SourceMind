from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from app.llm import ollama_provider
from app.llm.completion_control import (
    CompletionOptions,
    ProviderCancelledError,
    ProviderStreamError,
)
from app.llm.ollama_provider import OllamaProvider


class StreamingBody(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


class HangingBody(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        await asyncio.sleep(3600)
        yield b""


class OneChunkThenHangingBody(httpx.AsyncByteStream):
    def __init__(self, chunk: bytes):
        self._chunk = chunk

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._chunk
        await asyncio.sleep(3600)
        yield b""


def _line(payload: object) -> bytes:
    return json.dumps(payload).encode("utf-8") + b"\n"


def _install_ollama_stream(
    monkeypatch: pytest.MonkeyPatch,
    chunks: list[bytes],
) -> dict[str, Any]:
    captured: dict[str, Any] = {"requests": []}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["requests"].append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, stream=StreamingBody(chunks), request=request)

    class MockedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(ollama_provider.httpx, "AsyncClient", MockedAsyncClient)
    return captured


def run_fake_ollama_stream(
    monkeypatch: pytest.MonkeyPatch,
    lines: list[dict[str, Any]],
    *,
    response_schema: dict[str, Any] | None = None,
):
    if response_schema is None:
        response_schema = {"type": "array"}
    captured = _install_ollama_stream(monkeypatch, [_line(line) for line in lines])
    phases: list[str] = []
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    monkeypatch.setenv("SMV2_OLLAMA_BASE_URL", "http://fake-ollama:11434")
    provider = OllamaProvider()

    result = provider.complete(
        [{"role": "user", "content": "make json"}],
        max_tokens=8,
        purpose="cards",
        options=CompletionOptions(
            progress=lambda event: phases.append(event.phase),
            is_cancelled=lambda: False,
            response_schema=response_schema,
        ),
    )

    return result, captured["requests"][-1], phases


@pytest.mark.parametrize("thinking", ["private reasoning", ""])
def test_ollama_stream_discards_thinking_and_assembles_content(monkeypatch, thinking):
    lines = [
        {"message": {"thinking": thinking, "content": ""}, "done": False},
        {"message": {"thinking": "", "content": "["}, "done": False},
        {"message": {"thinking": "", "content": "]"}, "done": False},
        {"message": {"content": ""}, "done": True, "prompt_eval_count": 5, "eval_count": 2},
    ]
    result, captured, phases = run_fake_ollama_stream(monkeypatch, lines)
    assert result.text == "[]"
    if thinking:
        assert thinking not in result.text
    assert captured["stream"] is True
    assert captured["format"] == {"type": "array"}
    assert phases == ["loading", "thinking", "generating", "finalizing"]


def test_ollama_stream_rejects_malformed_lines_without_leaking_provider_data(monkeypatch):
    _install_ollama_stream(monkeypatch, [b'{"upstream":"secret"\n'])
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    provider = OllamaProvider()

    with pytest.raises(ProviderStreamError) as exc_info:
        provider.complete(
            [{"role": "user", "content": "make json"}],
            max_tokens=8,
            purpose="cards",
            options=CompletionOptions(),
        )

    assert exc_info.value.category == "ollama_malformed_chunk"
    assert exc_info.value.had_activity is False
    assert "secret" not in str(exc_info.value)


def test_ollama_stream_rejects_chunks_without_message_or_terminal_status(monkeypatch):
    _install_ollama_stream(monkeypatch, [_line({"upstream": "secret"})])
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    provider = OllamaProvider()

    with pytest.raises(ProviderStreamError) as exc_info:
        provider.complete(
            [{"role": "user", "content": "make json"}],
            max_tokens=8,
            purpose="cards",
            options=CompletionOptions(),
        )

    assert exc_info.value.category == "ollama_malformed_chunk"
    assert exc_info.value.had_activity is False
    assert "secret" not in str(exc_info.value)


def test_ollama_stream_rejects_model_error_chunks_without_leaking_provider_data(monkeypatch):
    _install_ollama_stream(monkeypatch, [_line({"error": "model runner stopped: secret-token"})])
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    provider = OllamaProvider()

    with pytest.raises(ProviderStreamError) as exc_info:
        provider.complete(
            [{"role": "user", "content": "make json"}],
            max_tokens=8,
            purpose="cards",
            options=CompletionOptions(),
        )

    assert exc_info.value.category == "ollama_model_error"
    assert exc_info.value.had_activity is False
    assert "secret-token" not in str(exc_info.value)


def test_ollama_stream_http_client_error_is_safe_and_not_retried(monkeypatch):
    captured = {"requests": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["requests"] += 1
        return httpx.Response(
            400,
            json={"error": "bad request includes secret-token"},
            request=request,
        )

    class MockedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(ollama_provider.httpx, "AsyncClient", MockedAsyncClient)
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    provider = OllamaProvider()

    with pytest.raises(ProviderStreamError) as exc_info:
        provider.complete(
            [{"role": "user", "content": "make json"}],
            max_tokens=8,
            purpose="cards",
            options=CompletionOptions(),
        )

    assert exc_info.value.category == "ollama_model_error"
    assert exc_info.value.had_activity is False
    assert captured["requests"] == 1
    assert "secret-token" not in str(exc_info.value)


def test_ollama_stream_cancellation_while_waiting_is_not_retried(monkeypatch):
    captured: dict[str, Any] = {"requests": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["requests"] += 1
        return httpx.Response(200, stream=HangingBody(), request=request)

    class MockedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    checks = {"count": 0}

    def is_cancelled() -> bool:
        checks["count"] += 1
        return checks["count"] > 1

    monkeypatch.setattr(ollama_provider.httpx, "AsyncClient", MockedAsyncClient)
    monkeypatch.setattr(ollama_provider, "_SUPERVISOR_TICK_SECONDS", 0.001)
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    provider = OllamaProvider()

    with pytest.raises(ProviderCancelledError):
        provider.complete(
            [{"role": "user", "content": "make json"}],
            max_tokens=8,
            purpose="cards",
            options=CompletionOptions(is_cancelled=is_cancelled),
        )

    assert captured["requests"] == 1


def test_ollama_stream_first_activity_timeout_is_retryable_before_any_activity(monkeypatch):
    captured: dict[str, Any] = {"requests": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["requests"] += 1
        if captured["requests"] == 1:
            return httpx.Response(200, stream=HangingBody(), request=request)
        return httpx.Response(
            200,
            stream=StreamingBody(
                [
                    _line({"message": {"content": "ok"}, "done": False}),
                    _line({"done": True, "prompt_eval_count": 1, "eval_count": 1}),
                ]
            ),
            request=request,
        )

    class MockedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monotonic_values = iter([0.0, 0.0, 301.0, 301.0, 301.0, 301.0, 301.0, 301.0, 301.0])
    monkeypatch.setattr(ollama_provider.httpx, "AsyncClient", MockedAsyncClient)
    monkeypatch.setattr(ollama_provider, "_SUPERVISOR_TICK_SECONDS", 0.001)
    monkeypatch.setattr(ollama_provider, "_monotonic", lambda: next(monotonic_values, 301.0))
    monkeypatch.setattr("app.llm.retry.time.sleep", lambda _seconds: None)
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    provider = OllamaProvider()

    result = provider.complete(
        [{"role": "user", "content": "make json"}],
        max_tokens=8,
        purpose="cards",
        options=CompletionOptions(),
    )

    assert result.text == "ok"
    assert captured["requests"] == 2


def test_ollama_stream_inactivity_timeout_after_activity_is_not_retried(monkeypatch):
    captured: dict[str, Any] = {"requests": []}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["requests"].append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            stream=OneChunkThenHangingBody(
                _line({"message": {"thinking": "private reasoning", "content": ""}, "done": False})
            ),
            request=request,
        )

    class MockedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monotonic_values = iter([0.0, 0.0, 0.0, 121.0])
    monkeypatch.setattr(ollama_provider.httpx, "AsyncClient", MockedAsyncClient)
    monkeypatch.setattr(ollama_provider, "_monotonic", lambda: next(monotonic_values, 121.0))
    monkeypatch.setattr(ollama_provider, "_SUPERVISOR_TICK_SECONDS", 0.001)
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    provider = OllamaProvider()

    with pytest.raises(ProviderStreamError) as exc_info:
        provider.complete(
            [{"role": "user", "content": "make json"}],
            max_tokens=8,
            purpose="cards",
            options=CompletionOptions(),
        )

    assert exc_info.value.category == "ollama_inactivity_timeout"
    assert exc_info.value.had_activity is True
    assert captured["requests"][-1]["stream"] is True


def test_ollama_stream_hard_deadline_fails_closed(monkeypatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=OneChunkThenHangingBody(
                _line({"message": {"content": "partial"}, "done": False})
            ),
            request=request,
        )

    class MockedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(*args, **kwargs)

    monotonic_values = iter([0.0, 0.0, 0.0, 1801.0])
    monkeypatch.setattr(ollama_provider.httpx, "AsyncClient", MockedAsyncClient)
    monkeypatch.setattr(ollama_provider, "_monotonic", lambda: next(monotonic_values, 1801.0))
    monkeypatch.setattr(ollama_provider, "_SUPERVISOR_TICK_SECONDS", 0.001)
    monkeypatch.setenv("SMV2_LLM_MODEL", "llama3.2")
    provider = OllamaProvider()

    with pytest.raises(ProviderStreamError) as exc_info:
        provider.complete(
            [{"role": "user", "content": "make json"}],
            max_tokens=8,
            purpose="cards",
            options=CompletionOptions(),
        )

    assert exc_info.value.category == "ollama_hard_wall_timeout"
    assert exc_info.value.had_activity is True
