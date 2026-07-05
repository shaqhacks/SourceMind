"""Uniform in-process concurrency guard for LLM/embedding transport calls.

Bounds the number of in-flight provider calls across the WHOLE process.
Previously this guard lived in ``routers/library.py`` and only wrapped the
chat and generate_course endpoints — background ingest (``run_materials_job``)
and lazy lesson generation (``run_lesson_job``) called the provider directly,
unbounded. Acquiring the slot here instead — inside
``ClaudeProvider``/``OllamaProvider.complete()`` and ``embed_text``/
``embed_texts`` — closes that gap: every call site is covered uniformly, and
there is exactly one semaphore to reason about (avoiding a double-acquire
deadlock that a second, router-level semaphore around the same calls would
risk once the pool is saturated).

A backstop, not full rate limiting: single-instance only, sized from
``config.max_concurrent_llm()`` (default 4). There is no caller-visible
fast-fail (429) path anymore — every acquire blocks until a slot frees up,
since the acquisition now happens deep enough in the call stack (inside the
provider/embedding call itself) that callers have no opportunity to choose
otherwise.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

from SourceMind.backend import config

_semaphore = threading.BoundedSemaphore(config.max_concurrent_llm())


@contextmanager
def llm_slot():
    """Acquire a concurrency slot for the duration of one LLM/embed call.

    Blocks until a slot frees up when the pool is saturated.
    """
    _semaphore.acquire()
    try:
        yield
    finally:
        _semaphore.release()
