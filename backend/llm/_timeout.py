"""Shared timeout + classified-retry wrapper for LLM transport calls.

A hung provider call (no network timeout) blocks a worker forever. This module
runs the transport callable in a daemon thread and abandons it after
``SOURCEMIND_LLM_TIMEOUT`` seconds (default 120). Daemon threads never block
interpreter exit, so a genuinely hung call leaks a background thread rather
than wedging shutdown — an acceptable backstop for a single-instance local
service. There is no way to cancel a raw Python thread; a hung call's thread
keeps running (and its result is discarded) until it happens to return.

Retries are classified, not blanket: transient transport failures (timeouts,
connection errors, 5xx) are retried with exponential backoff + jitter;
non-transient failures (4xx like bad-request/auth) raise immediately since a
retry would fail identically. Where the provider SDK itself accepts a native
per-call timeout (the ``anthropic`` client's ``messages.create(timeout=...)``,
already passed through by :mod:`SourceMind.backend.llm.claude`), prefer that —
this thread-join timeout is the fallback for transports that don't offer one
(or as a backstop against a transport that ignores its own timeout).

Both :mod:`SourceMind.backend.llm.claude` and
:mod:`SourceMind.backend.llm.ollama` (and embeddings) route their transport
through :func:`call_with_timeout_retry` so the timeout/retry behavior is
uniform and independently testable with stubbed transports.
"""
from __future__ import annotations

import random
import threading
import time
from typing import Callable, TypeVar

from SourceMind.backend import config

T = TypeVar("T")

_DEFAULT_ATTEMPTS = 2


def llm_timeout() -> float:
    """Per-call wall-clock budget in seconds (env ``SOURCEMIND_LLM_TIMEOUT``)."""
    return config.llm_timeout()


def _is_transient(exc: BaseException) -> bool:
    """Classify whether *exc* is a transient/retryable transport failure.

    Retryable: our own timeout marker, generic connection errors, and either
    backend SDK's timeout/connection errors or 5xx status errors. NOT
    retryable: 4xx errors (bad request, auth, not found, rate limit, ...) —
    retrying would fail identically and only burns time/quota.
    """
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True

    try:
        import anthropic
    except ImportError:  # pragma: no cover - anthropic is a hard dependency
        pass
    else:
        # APIConnectionError also covers APITimeoutError (its subclass).
        if isinstance(exc, anthropic.APIConnectionError):
            return True
        if isinstance(exc, anthropic.APIStatusError):
            return exc.status_code >= 500

    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx is a hard dependency
        pass
    else:
        # TransportError covers Connect/Read/Write/PoolTimeout and ConnectError.
        if isinstance(exc, httpx.TransportError):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code >= 500

    return False


def _backoff_delay(attempt_index: int, base: float) -> float:
    """Exponential backoff with jitter: ``base * 2**attempt_index``, randomized
    to within [0.5x, 1.5x) so concurrent retries don't all wake in lockstep."""
    delay = base * (2**attempt_index)
    return delay * (0.5 + random.random())


def call_with_timeout_retry(
    fn: Callable[[], T],
    *,
    attempts: int = _DEFAULT_ATTEMPTS,
    timeout: float | None = None,
) -> T:
    """Call ``fn`` with a join-timeout, retrying transient failures with backoff.

    Runs ``fn`` in a daemon thread and waits up to ``timeout`` seconds
    (defaults to :func:`llm_timeout`). On timeout, retries (total ``attempts``
    tries, exponential backoff + jitter between them) before re-raising the
    last timeout. On an exception from ``fn``, retries the same way only when
    :func:`_is_transient` classifies it as transient; a non-transient
    exception raises immediately without consuming a retry.
    """
    budget = llm_timeout() if timeout is None else timeout
    backoff_base = config.llm_retry_backoff_base()
    last_exc: BaseException | None = None
    total_attempts = max(1, attempts)

    for attempt_index in range(total_attempts):
        result: dict[str, T] = {}
        error: dict[str, BaseException] = {}

        # Bind result/error as defaults so a still-alive thread from a previous
        # (timed-out) attempt writes into ITS OWN dicts, never a later attempt's
        # freshly-rebound ones — avoids a late-binding cross-attempt race.
        def _runner(_result=result, _error=error) -> None:
            try:
                _result["value"] = fn()
            except BaseException as exc:  # noqa: BLE001 - surfaced via _error
                _error["exc"] = exc

        worker = threading.Thread(target=_runner, daemon=True)
        worker.start()
        worker.join(budget)

        if worker.is_alive():
            last_exc = TimeoutError(f"LLM call exceeded {budget}s timeout")
        elif "exc" in error:
            exc = error["exc"]
            # Never retry fatal control-flow exceptions — propagate immediately.
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise exc
            if not _is_transient(exc):
                raise exc
            last_exc = exc
        else:
            return result["value"]

        if attempt_index < total_attempts - 1:
            time.sleep(_backoff_delay(attempt_index, backoff_base))

    assert last_exc is not None  # loop runs >=1 time and only continues on failure
    raise last_exc
