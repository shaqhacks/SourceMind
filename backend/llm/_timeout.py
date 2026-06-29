"""Shared timeout + light-retry wrapper for LLM transport calls.

A hung provider call (no network timeout) blocks a worker forever. This module
runs the transport callable in a daemon thread and abandons it after
``SOURCEMIND_LLM_TIMEOUT`` seconds (default 120), retrying once on any transient
error/timeout before raising. Daemon threads never block interpreter exit, so a
genuinely hung call leaks a background thread rather than wedging shutdown — an
acceptable backstop for a single-instance local service.

Both :mod:`SourceMind.backend.llm.claude` and
:mod:`SourceMind.backend.llm.ollama` (and embeddings) route their transport
through :func:`call_with_timeout_retry` so the timeout/retry behavior is
uniform and independently testable with stubbed transports.
"""
from __future__ import annotations

import os
import threading
from typing import Callable, TypeVar

T = TypeVar("T")

_DEFAULT_TIMEOUT = 120.0
_DEFAULT_ATTEMPTS = 2


def llm_timeout() -> float:
    """Per-call wall-clock budget in seconds (env ``SOURCEMIND_LLM_TIMEOUT``)."""
    try:
        value = float(os.environ.get("SOURCEMIND_LLM_TIMEOUT", _DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT
    return value if value > 0 else _DEFAULT_TIMEOUT


def call_with_timeout_retry(
    fn: Callable[[], T],
    *,
    attempts: int = _DEFAULT_ATTEMPTS,
    timeout: float | None = None,
) -> T:
    """Call ``fn`` with a join-timeout, retrying once on error/timeout.

    Runs ``fn`` in a daemon thread and waits up to ``timeout`` seconds. On
    timeout or any exception, retries (total ``attempts`` tries) before
    re-raising the last error. The timeout defaults to :func:`llm_timeout`.
    """
    budget = llm_timeout() if timeout is None else timeout
    last_exc: BaseException | None = None

    for _ in range(max(1, attempts)):
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
            continue
        if "exc" in error:
            exc = error["exc"]
            # Never retry fatal control-flow exceptions — propagate immediately.
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise exc
            last_exc = exc
            continue
        return result["value"]

    assert last_exc is not None  # loop runs >=1 time and only continues on failure
    raise last_exc
