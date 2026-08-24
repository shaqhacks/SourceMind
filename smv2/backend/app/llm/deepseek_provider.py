"""DeepSeek-backed Provider.

DeepSeek's API is OpenAI-compatible (`/chat/completions`); we talk to it
directly over httpx rather than pulling in an SDK, mirroring the
ollama_provider's plain-http approach. It has no embeddings endpoint, so
`supports_embeddings` stays False (same as Anthropic).

httpx exceptions are left to propagate raw — `app/llm/retry._is_transient`
already recognizes httpx.ConnectError/ReadTimeout/TimeoutException and
HTTPStatusError >= 500, so this provider inherits the single retry authority
without any of its own. 401/403 are converted to ProviderNotConfiguredError
(a rejected key is a config problem, never retryable).
"""

from __future__ import annotations

import time

import httpx

from app.config import deepseek_api_key, llm_model
from app.llm.completion_control import (
    CompletionOptions,
    CompletionPhase,
    CompletionProgress,
    ProviderCancelledError,
)
from app.llm.provider import (
    CompletionResult,
    NotSupportedError,
    Provider,
    ProviderNotConfiguredError,
)

_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
_TIMEOUT_SECONDS = 600.0

_DEEPSEEK_NOT_CONFIGURED_MESSAGE = (
    "LLM provider not configured: add deepseek_api_key to data/secrets.toml "
    "or set DEEPSEEK_API_KEY."
)


class DeepSeekProvider(Provider):
    supports_embeddings = False  # DeepSeek has no embeddings API

    def __init__(self, model: str | None = None) -> None:
        self.model_name = model or llm_model()
        self._api_key = deepseek_api_key()
        if self._api_key is None:
            raise ProviderNotConfiguredError(_DEEPSEEK_NOT_CONFIGURED_MESSAGE)

    def _complete_impl(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        options: CompletionOptions,
        system: str | None = None,
    ) -> CompletionResult:
        started = time.monotonic()

        def _emit_progress(phase: CompletionPhase) -> None:
            if options.progress is None:
                return
            options.progress(
                CompletionProgress(
                    phase=phase,
                    elapsed_seconds=max(0.0, time.monotonic() - started),
                    seconds_since_activity=0.0,
                )
            )

        if options.is_cancelled is not None and options.is_cancelled():
            raise ProviderCancelledError()
        _emit_progress("loading")

        full_messages = (
            [{"role": "system", "content": system}, *messages]
            if system is not None
            else messages
        )
        payload: dict = {
            "model": self.model_name,
            "messages": full_messages,
            "max_tokens": max_tokens,
        }
        if options.response_schema is not None and "reasoner" not in self.model_name:
            # DeepSeek supports JSON mode (json_object), not arbitrary JSON
            # schema. This biases output toward valid JSON for the structured
            # paths (cards/quiz/curriculum); callers still validate + retry.
            # deepseek-reasoner does NOT support response_format (and can't
            # reliably emit structured JSON) — never send it there, and use
            # deepseek-chat for structured generation instead.
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = httpx.post(
                f"{_DEEPSEEK_BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
                timeout=_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code in (401, 403):
                raise ProviderNotConfiguredError(_DEEPSEEK_NOT_CONFIGURED_MESSAGE) from exc
            raise

        data = response.json()
        choice = data["choices"][0]
        message = choice["message"]
        text = message.get("content") or ""
        usage = data.get("usage") or {}
        _emit_progress("finalizing")
        return CompletionResult(
            text=text,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            model=data.get("model") or self.model_name,
        )

    def _embed_impl(self, texts: list[str]) -> list[list[float] | None]:
        raise NotSupportedError("DeepSeek has no embeddings API")
