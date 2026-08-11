from __future__ import annotations

import httpx
import pytest

from app.llm.completion_control import ProviderCancelledError, ProviderStreamError
from app.llm.retry import retry_transient


def _http_error(status_code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://example.invalid")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("error", request=request, response=response)


def test_retry_transient_succeeds_after_one_transient_failure():
    calls = {"count": 0}

    def flaky():
        calls["count"] += 1
        if calls["count"] == 1:
            raise _http_error(503)
        return "success"

    result = retry_transient(flaky)

    assert result == "success"
    assert calls["count"] == 2


def test_retry_transient_does_not_retry_non_transient_4xx():
    calls = {"count": 0}

    def always_bad_request():
        calls["count"] += 1
        raise _http_error(400)

    with pytest.raises(httpx.HTTPStatusError):
        retry_transient(always_bad_request)

    assert calls["count"] == 1


def test_retry_transient_gives_up_after_max_attempts():
    calls = {"count": 0}

    def always_flaky():
        calls["count"] += 1
        raise _http_error(500)

    with pytest.raises(httpx.HTTPStatusError):
        retry_transient(always_flaky)

    assert calls["count"] == 2  # max 2 total attempts, then it gives up


def test_retry_transient_treats_connect_error_as_transient():
    calls = {"count": 0}

    def flaky_connection():
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ConnectError("connection refused")
        return "ok"

    assert retry_transient(flaky_connection) == "ok"
    assert calls["count"] == 2


@pytest.mark.parametrize(
    "category",
    ["ollama_connect_error", "ollama_first_activity_timeout", "ollama_transport_error"],
)
def test_retry_transient_retries_stream_error_only_before_any_activity(category):
    calls = {"count": 0}

    def flaky_stream():
        calls["count"] += 1
        if calls["count"] == 1:
            raise ProviderStreamError("stream did not start", category=category, had_activity=False)
        return "ok"

    assert retry_transient(flaky_stream) == "ok"
    assert calls["count"] == 2


@pytest.mark.parametrize(
    "category",
    [
        "ollama_inactivity_timeout",
        "ollama_hard_wall_timeout",
        "ollama_model_error",
        "ollama_malformed_chunk",
    ],
)
def test_retry_transient_does_not_retry_stream_errors_after_activity_or_final_failures(category):
    calls = {"count": 0}

    def failed_stream():
        calls["count"] += 1
        raise ProviderStreamError("stream stopped", category=category, had_activity=True)

    with pytest.raises(ProviderStreamError):
        retry_transient(failed_stream)

    assert calls["count"] == 1


def test_retry_transient_does_not_retry_provider_cancellation():
    calls = {"count": 0}

    def cancelled():
        calls["count"] += 1
        raise ProviderCancelledError()

    with pytest.raises(ProviderCancelledError):
        retry_transient(cancelled)

    assert calls["count"] == 1
