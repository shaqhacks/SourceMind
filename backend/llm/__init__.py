"""LLM provider abstraction for SourceMind."""
from SourceMind.backend.llm.provider import LLMProvider, get_provider, DEFAULT_CLAUDE_MODEL
from SourceMind.backend.llm.claude import ClaudeProvider
from SourceMind.backend.llm.ollama import OllamaProvider

__all__ = ["LLMProvider", "ClaudeProvider", "OllamaProvider", "get_provider", "DEFAULT_CLAUDE_MODEL"]
