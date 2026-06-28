"""Provider Protocol and factory for LLM backends."""
from __future__ import annotations

import os
from typing import Protocol, runtime_checkable

DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"


@runtime_checkable
class LLMProvider(Protocol):
    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        schema: dict | None = None,
        max_tokens: int = 4096,
    ) -> str | dict: ...


def get_provider() -> LLMProvider:
    """Factory: reads env vars to select and instantiate the right provider."""
    provider_name = os.environ.get("SOURCEMIND_LLM_PROVIDER", "claude").lower()

    if provider_name == "ollama":
        from SourceMind.backend.llm.ollama import OllamaProvider
        model = os.environ.get("SOURCEMIND_LLM_MODEL", "llama3.1")
        return OllamaProvider(model=model)

    # Default: Claude
    from SourceMind.backend.llm.claude import ClaudeProvider
    model = os.environ.get("SOURCEMIND_LLM_MODEL", DEFAULT_CLAUDE_MODEL)
    return ClaudeProvider(model=model)
