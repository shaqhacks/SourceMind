"""Transient-only retry for LLM provider calls.

Retries timeouts/connection errors/5xx up to _MAX_ATTEMPTS total calls (one
retry). Never retries a 4xx or any other non-transient error — a bad
request would just double-bill without ever succeeding.
"""

from __future__ import annotations

import time
from typing import Callable, TypeVar

import httpx

T = TypeVar("T")

_MAX_ATTEMPTS = 2
_BACKOFF_SECONDS = 0.5


def _is_transient(exc: Exception) -> bool:
    try:
        import anthropic

        if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
            return True
        if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
            return True
    except ImportError:
        pass

    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.TimeoutException)):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None and exc.response.status_code >= 500:
        return True

    return False


def retry_transient(fn: Callable[[], T]) -> T:
    attempt = 1
    while True:
        try:
            return fn()
        except Exception as exc:
            if attempt >= _MAX_ATTEMPTS or not _is_transient(exc):
                raise
            time.sleep(_BACKOFF_SECONDS * attempt)
            attempt += 1


def is_timeout(exc: Exception) -> bool:
    """Lets callers outside app/llm/ (e.g. chat_service, mapping a timeout
    to an HTTP 504) recognize a provider timeout without themselves
    importing the anthropic/httpx SDK types directly — those imports stay
    confined to app/llm/.
    """
    try:
        import anthropic

        if isinstance(exc, anthropic.APITimeoutError):
            return True
    except ImportError:
        pass
    return isinstance(exc, httpx.TimeoutException)
