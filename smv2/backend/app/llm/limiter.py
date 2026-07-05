"""The one sanctioned concurrency primitive in this codebase (hard
invariant — see CLAUDE.md and test_no_threading_or_semaphore_usage's
limiter exception). llm_slot() is a non-blocking gate: when saturated it
raises immediately rather than queuing, so a caller (a router) can turn
that straight into a fast 429 instead of hanging a request thread.

The semaphore is a lazily-built, cached singleton (mirrors
app.db.engine.get_engine()/dispose_engine()) rather than a module-scope
constant, so it still respects lazy config — llm_max_concurrency() is read
on first use, not at import time. reset_limiter() lets tests force a
rebuild after monkeypatching the concurrency env var.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from app.config import llm_max_concurrency

_semaphore: threading.BoundedSemaphore | None = None


class LLMBusyError(Exception):
    pass


def _get_semaphore() -> threading.BoundedSemaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = threading.BoundedSemaphore(llm_max_concurrency())
    return _semaphore


def reset_limiter() -> None:
    global _semaphore
    _semaphore = None


@contextmanager
def llm_slot() -> Iterator[None]:
    semaphore = _get_semaphore()
    if not semaphore.acquire(blocking=False):
        raise LLMBusyError("LLM concurrency limit reached")
    try:
        yield
    finally:
        semaphore.release()
