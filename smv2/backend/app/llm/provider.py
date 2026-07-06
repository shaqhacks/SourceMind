"""LLM provider abstraction.

Provider is a template-method base class: complete()/embed() handle
concurrency (llm_slot), transient retry, timing, and the ledger write
uniformly, so no call path can accidentally skip any of those — concrete
providers (and test stubs) only implement _complete_impl()/_embed_impl().
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


class NotSupportedError(Exception):
    """Raised by a provider that has no API for the requested capability
    (e.g. Anthropic has no embeddings endpoint)."""


class ProviderTimeoutError(Exception):
    """Generic, SDK-agnostic timeout signal — lets callers outside
    app/llm/ (routers, services) catch a provider timeout and map it to an
    HTTP status without importing anthropic/httpx types themselves."""


PROVIDER_NOT_CONFIGURED_MESSAGE = (
    "LLM provider not configured: set ANTHROPIC_API_KEY, or set "
    "SMV2_LLM_PROVIDER=ollama with a local Ollama running."
)


class ProviderNotConfiguredError(Exception):
    """Raised when the configured provider has no usable credentials/
    connection at all (e.g. ANTHROPIC_API_KEY unset) — generic, SDK-agnostic,
    same reasoning as ProviderTimeoutError above. Never retried: it isn't one
    of retry.py's recognized transient types, so it's a single, final
    failure. Carries a friendly, actionable message instead of letting the
    raw SDK error reach job.error or a chat response."""


class Provider(ABC):
    #: Concrete providers set this in __init__; used for the ledger row on
    #: the error path, where there's no CompletionResult.model to read from.
    model_name: str = "unknown"
    #: False by default (matches the base _embed_impl's no-op). Callers that
    #: only want to embed when it will actually work (e.g. chat's lazy
    #: embed_course trigger) should check this rather than enqueue a job
    #: doomed to no-op against a provider with no embeddings API at all.
    supports_embeddings: bool = False

    def complete(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        purpose: str,
        course_id: str | None = None,
        prompt_version: str | None = None,
        system: str | None = None,
        wait_for_slot: bool = False,
    ) -> CompletionResult:
        """wait_for_slot=True makes a saturated limiter block (bounded) for a
        slot instead of fast-failing — durable job-context callers (lesson/
        cards/quiz generation) would rather wait out a busy patch than fail
        an entire job over transient interactive (chat) traffic. Interactive
        callers keep the default fast-fail so a busy limiter turns into an
        immediate, honest 429 rather than a hung request.
        """
        with llm_slot(wait=wait_for_slot):
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

    def embed(
        self,
        texts: list[str],
        *,
        purpose: str = "embed",
        course_id: str | None = None,
        wait_for_slot: bool = False,
    ) -> list[list[float] | None]:
        """Same concurrency/ledger discipline as complete(). Unlike
        complete(), a provider-level failure here (e.g. NotSupportedError)
        is NOT swallowed — callers (embed_course, retrieval) decide how to
        degrade (skip embedding entirely, fall back to lexical search).
        wait_for_slot=True: see complete()'s docstring — the durable
        embed_course job passes True, interactive retrieval keeps fast-fail.
        """
        with llm_slot(wait=wait_for_slot):
            started = time.monotonic()
            try:
                results = self._embed_impl(texts)
            except Exception as exc:
                latency_ms = int((time.monotonic() - started) * 1000)
                self._record_call_safely(
                    purpose=purpose,
                    model=self.model_name,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=latency_ms,
                    cost_estimate=None,
                    prompt_version=None,
                    status="error",
                    course_id=course_id,
                )
                raise exc

            latency_ms = int((time.monotonic() - started) * 1000)
            input_tokens_est = sum(len(t) for t in texts) // 4
            self._record_call_safely(
                purpose=purpose,
                model=self.model_name,
                input_tokens=input_tokens_est,
                output_tokens=0,
                latency_ms=latency_ms,
                cost_estimate=estimate_cost(self.model_name, input_tokens_est, 0),
                prompt_version=None,
                status="ok",
                course_id=course_id,
            )
            return results

    def _embed_impl(self, texts: list[str]) -> list[list[float] | None]:
        """Default: no embedding support. Override in a provider with a
        real embeddings API (raise NotSupportedError if there truly is
        none, as AnthropicProvider does)."""
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
