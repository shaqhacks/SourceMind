"""LLM provider abstraction.

Provider is a template-method base class: complete() handles concurrency
(llm_slot), transient retry, timing, and the ledger write uniformly, so no
call path can accidentally skip any of those — concrete providers (and test
stubs) only implement _complete_impl(). embed() is a working placeholder
for Phase 3 (returns None per text); real embeddings arrive in Phase 4.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import llm_provider
from app.llm.ledger import record_llm_call
from app.llm.limiter import llm_slot
from app.llm.pricing import estimate_cost
from app.llm.retry import retry_transient

logger = logging.getLogger(__name__)


@dataclass
class CompletionResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class Provider(ABC):
    #: Concrete providers set this in __init__; used for the ledger row on
    #: the error path, where there's no CompletionResult.model to read from.
    model_name: str = "unknown"

    def complete(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        purpose: str,
        course_id: str | None = None,
        prompt_version: str | None = None,
        system: str | None = None,
    ) -> CompletionResult:
        with llm_slot():
            started = time.monotonic()
            try:
                result = retry_transient(
                    lambda: self._complete_impl(messages, max_tokens=max_tokens, system=system)
                )
            except Exception as exc:
                latency_ms = int((time.monotonic() - started) * 1000)
                self._record_call_safely(
                    purpose=purpose,
                    model=self.model_name,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=latency_ms,
                    cost_estimate=None,
                    prompt_version=prompt_version,
                    status="error",
                    course_id=course_id,
                )
                raise exc

            latency_ms = int((time.monotonic() - started) * 1000)
            cost = estimate_cost(result.model, result.input_tokens, result.output_tokens)
            self._record_call_safely(
                purpose=purpose,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=latency_ms,
                cost_estimate=cost,
                prompt_version=prompt_version,
                status="ok",
                course_id=course_id,
            )
            return result

    @staticmethod
    def _record_call_safely(**kwargs) -> None:
        """The ledger write must never destroy a completion the caller
        already paid for (success path), nor mask the original provider
        error (failure path) — a broken ledger write is logged and
        swallowed here rather than propagated.
        """
        try:
            record_llm_call(**kwargs)
        except Exception:
            logger.exception("failed to write llm_calls ledger row")

    @abstractmethod
    def _complete_impl(
        self, messages: list[dict], *, max_tokens: int, system: str | None = None
    ) -> CompletionResult: ...

    def embed(self, texts: list[str]) -> list[list[float] | None]:
        """Placeholder for Phase 4 — always returns None per text for now,
        but still goes through the concurrency gate for interface parity.
        """
        with llm_slot():
            return [None for _ in texts]


def get_provider() -> Provider:
    backend = llm_provider()
    if backend == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider()
    if backend == "ollama":
        from app.llm.ollama_provider import OllamaProvider

        return OllamaProvider()
    raise ValueError(f"unknown LLM provider: {backend}")
