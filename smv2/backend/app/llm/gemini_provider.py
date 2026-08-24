"""Gemini-backed Provider.

Google's Gemini API (the model that powers NotebookLM) is called directly over
httpx — no SDK dependency, mirroring the deepseek/ollama providers. It has
both a completion endpoint (`:generateContent`) and an embeddings endpoint
(`:embedContent`), so `supports_embeddings` is True.

httpx exceptions are left to propagate raw — `app.llm.retry._is_transient`
already recognizes httpx.ConnectError/ReadTimeout/TimeoutException and
HTTPStatusError >= 500, so this provider inherits the single retry authority.
401/403 are converted to ProviderNotConfiguredError (a rejected key is a
config problem, never retryable).
"""

from __future__ import annotations

import time

import httpx

from app.config import gemini_api_key, gemini_embed_model, llm_model
from app.llm.completion_control import (
    CompletionOptions,
    CompletionPhase,
    CompletionProgress,
    ProviderCancelledError,
)
from app.llm.provider import (
    CompletionResult,
    Provider,
    ProviderNotConfiguredError,
)
from app.llm.retry import retry_transient

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"
_TIMEOUT_SECONDS = 600.0

_GEMINI_NOT_CONFIGURED_MESSAGE = (
    "LLM provider not configured: add gemini_api_key to data/secrets.toml "
    "or set GEMINI_API_KEY."
)


def _to_gemini_contents(messages: list[dict]) -> list[dict]:
    """Map OpenAI-style role messages to Gemini `contents` (Gemini uses
    "model" for assistant turns and `parts` for the text)."""
    contents = []
    for message in messages:
        role = "model" if message.get("role") == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": message["content"]}]})
    return contents


class GeminiProvider(Provider):
    supports_embeddings = True

    def __init__(self, model: str | None = None) -> None:
        self.model_name = model or llm_model()
        self._api_key = gemini_api_key()
        if self._api_key is None:
            raise ProviderNotConfiguredError(_GEMINI_NOT_CONFIGURED_MESSAGE)

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

        payload: dict = {
            "contents": _to_gemini_contents(messages),
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        if system is not None:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if options.response_schema is not None:
            # JSON mode only (not the full schema): the existing schemas use
            # `"type": ["string","null"]` unions that Gemini's OpenAPI subset
            # rejects, so we rely on the prompt + the caller's validate-and-
            # retry, same as the deepseek provider.
            payload["generationConfig"]["responseMimeType"] = "application/json"

        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        url = f"{_GEMINI_BASE_URL}/v1beta/models/{self.model_name}:generateContent"
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=_TIMEOUT_SECONDS)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code in (401, 403):
                raise ProviderNotConfiguredError(_GEMINI_NOT_CONFIGURED_MESSAGE) from exc
            raise

        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise ProviderNotConfiguredError(_GEMINI_NOT_CONFIGURED_MESSAGE) from RuntimeError(
                "Gemini returned no candidates"
            )
        parts = candidates[0].get("content", {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
        usage = data.get("usageMetadata") or {}
        _emit_progress("finalizing")
        return CompletionResult(
            text=text,
            input_tokens=int(usage.get("promptTokenCount", 0)),
            output_tokens=int(usage.get("candidatesTokenCount", 0)),
            model=data.get("modelVersion") or self.model_name,
        )

    def _embed_impl(self, texts: list[str]) -> list[list[float] | None]:
        model = gemini_embed_model()
        results: list[list[float] | None] = []
        for text in texts:
            try:
                results.append(retry_transient(lambda t=text: self._embed_one(t, model)))
            except Exception:
                results.append(None)
        return results

    def _embed_one(self, text: str, model: str) -> list[float]:
        headers = {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}
        url = f"{_GEMINI_BASE_URL}/v1beta/models/{model}:embedContent"
        response = httpx.post(
            url,
            json={"content": {"parts": [{"text": text}]}},
            headers=headers,
            timeout=_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        return list(data["embedding"]["values"])
