from __future__ import annotations

import threading

import pytest

from app.llm.limiter import LLMBusyError, reset_limiter
from app.llm.provider import CompletionResult, Provider


class _BlockingProvider(Provider):
    """A Provider whose _complete_impl blocks until released — used to hold
    concurrency slots open long enough to deterministically saturate them.
    """

    def __init__(self, entered_barrier: threading.Barrier, release_event: threading.Event) -> None:
        self.model_name = "blocking-stub"
        self._entered_barrier = entered_barrier
        self._release_event = release_event

    def _complete_impl(self, messages, *, max_tokens, system=None):
        # Reaching this point proves the semaphore slot was already
        # acquired (llm_slot() wraps this call) — the barrier lets the main
        # thread know both workers are holding a slot before it tries a 3rd.
        self._entered_barrier.wait(timeout=5)
        self._release_event.wait(timeout=5)
        return CompletionResult(text="ok", input_tokens=1, output_tokens=1, model=self.model_name)


def test_llm_slot_raises_busy_when_saturated_without_blocking(client, monkeypatch):
    monkeypatch.setenv("SMV2_LLM_MAX_CONCURRENCY", "2")
    reset_limiter()

    entered_barrier = threading.Barrier(3)  # 2 workers + this test thread
    release_event = threading.Event()
    provider = _BlockingProvider(entered_barrier, release_event)

    def _worker():
        provider.complete([{"role": "user", "content": "x"}], max_tokens=10, purpose="test")

    threads = [threading.Thread(target=_worker) for _ in range(2)]
    for t in threads:
        t.start()

    # Blocks until both workers have acquired their slot and entered
    # _complete_impl — after this returns, both of the 2 available slots
    # are guaranteed held.
    entered_barrier.wait(timeout=5)

    try:
        with pytest.raises(LLMBusyError):
            provider.complete([{"role": "user", "content": "y"}], max_tokens=10, purpose="test")
    finally:
        release_event.set()
        for t in threads:
            t.join(timeout=5)
        reset_limiter()


def test_llm_slot_is_available_again_after_release(client, monkeypatch):
    monkeypatch.setenv("SMV2_LLM_MAX_CONCURRENCY", "1")
    reset_limiter()

    from app.llm.limiter import llm_slot

    with llm_slot():
        pass  # acquired and released cleanly

    with llm_slot():
        pass  # slot must be available again, not permanently consumed

    reset_limiter()
