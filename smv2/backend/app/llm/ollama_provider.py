"""Ollama-backed Provider — plain httpx against the Ollama HTTP API. No
`ollama` package dependency, deliberately: one fewer moving part, and the
chat/embeddings API surface is small enough that httpx directly is simpler.
"""

from __future__ import annotations

import logging

import httpx

from app.config import embed_model, llm_model, ollama_base_url
from app.llm.provider import CompletionResult, Provider
from app.llm.retry import retry_transient

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT_SECONDS = 120.0


class OllamaProvider(Provider):
    def __init__(self) -> None:
        self.model_name = llm_model()
        self.base_url = ollama_base_url()

    def _complete_impl(
        self, messages: list[dict], *, max_tokens: int, system: str | None = None
    ) -> CompletionResult:
        full_messages = [{"role": "system", "content": system}, *messages] if system is not None else messages
        response = httpx.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model_name,
                "messages": full_messages,
                "stream": False,
                "options": {"num_predict": max_tokens},
            },
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        text = (data.get("message") or {}).get("content", "")
        return CompletionResult(
            text=text,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            model=self.model_name,
        )

    def _embed_impl(self, texts: list[str]) -> list[list[float] | None]:
        """One request per text, sharing the same transient-retry policy as
        complete(). Per-item isolation: a failure on one text (even after
        its own retry) leaves that entry None rather than failing the
        whole batch — callers (embed_course) treat that chunk as still
        unembedded and move on.
        """
        model = embed_model()
        results: list[list[float] | None] = []
        for text in texts:
            try:
                results.append(retry_transient(lambda t=text: self._embed_one(t, model)))
            except Exception:
                logger.exception("embedding failed for one text; leaving it null")
                results.append(None)
        return results

    def _embed_one(self, text: str, model: str) -> list[float]:
        response = httpx.post(
            f"{self.base_url}/api/embeddings",
            json={"model": model, "prompt": text},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
        return data["embedding"]
