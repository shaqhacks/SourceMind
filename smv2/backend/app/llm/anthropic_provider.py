"""Anthropic-backed Provider. Only this module (and ollama_provider.py) is
allowed to import the anthropic/httpx-to-ollama SDKs — see
test_llm_sdk_imports_confined_to_llm_package.
"""

from __future__ import annotations

import anthropic

from app.config import llm_model
from app.llm.provider import CompletionResult, Provider


class AnthropicProvider(Provider):
    def __init__(self) -> None:
        self.model_name = llm_model()
        # max_retries=0: the SDK defaults to retrying transient errors itself,
        # which would compound with app.llm.retry's own retry_transient() and
        # violate "one retry mechanism, never double-retry" — retry.py is the
        # sole retry authority for every provider.
        self._client = anthropic.Anthropic(max_retries=0)

    def _complete_impl(
        self, messages: list[dict], *, max_tokens: int, system: str | None = None
    ) -> CompletionResult:
        kwargs: dict = {"model": self.model_name, "max_tokens": max_tokens, "messages": messages}
        if system is not None:
            kwargs["system"] = system
        response = self._client.messages.create(**kwargs)
        text = "".join(block.text for block in response.content if block.type == "text")
        return CompletionResult(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=response.model,
        )
