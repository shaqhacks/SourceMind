"""Provider Protocol and factory for LLM backends."""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from SourceMind.backend import config

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
    provider_name = config.llm_provider()

    if provider_name == "ollama":
        from SourceMind.backend.llm.ollama import OllamaProvider
        model = config.llm_model("llama3.1")
        return OllamaProvider(model=model)

    # Default: Claude
    from SourceMind.backend.llm.claude import ClaudeProvider
    model = config.llm_model(DEFAULT_CLAUDE_MODEL)
    return ClaudeProvider(model=model)
