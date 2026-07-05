from __future__ import annotations

import httpx
import pytest

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
