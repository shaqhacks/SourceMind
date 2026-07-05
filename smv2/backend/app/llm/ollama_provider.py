"""Ollama-backed Provider — plain httpx against the Ollama HTTP API. No
`ollama` package dependency, deliberately: one fewer moving part, and the
chat API surface is small enough that httpx directly is simpler.
"""

from __future__ import annotations

import httpx

from app.config import llm_model, ollama_base_url
from app.llm.provider import CompletionResult, Provider

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
