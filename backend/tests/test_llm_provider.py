"""Tests for the pluggable LLM provider abstraction."""
from __future__ import annotations

import types
import pytest


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------

def test_factory_selects_ollama(monkeypatch):
    monkeypatch.setenv("SOURCEMIND_LLM_PROVIDER", "ollama")
    from SourceMind.backend.llm import provider
    p = provider.get_provider()
    assert p.__class__.__name__ == "OllamaProvider"


def test_factory_defaults_to_claude(monkeypatch):
    monkeypatch.delenv("SOURCEMIND_LLM_PROVIDER", raising=False)
    from SourceMind.backend.llm import provider
    p = provider.get_provider()
    assert p.__class__.__name__ == "ClaudeProvider"


# ---------------------------------------------------------------------------
# ClaudeProvider transport stubs
# ---------------------------------------------------------------------------

class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeToolUseBlock:
    def __init__(self, data):
        self.type = "tool_use"
        self.input = data


class _FakeResponse:
    def __init__(self, blocks):
        self.content = blocks


def _make_fake_anthropic(text_response=None, tool_response=None):
    """Return a fake anthropic module with a stubbed Anthropic client."""

    def fake_create(**kwargs):
        if "tools" in kwargs:
            return _FakeResponse([_FakeToolUseBlock(tool_response or {"answer": 42})])
        return _FakeResponse([_FakeTextBlock(text_response or "hello")])

    fake_messages = types.SimpleNamespace(create=fake_create)
    fake_client = types.SimpleNamespace(messages=fake_messages)
    fake_anthropic_cls = lambda: fake_client  # noqa: E731

    return types.ModuleType("anthropic"), fake_anthropic_cls


def test_claude_complete_text(monkeypatch):
    import importlib
    import sys

    # Ensure module loaded
    from SourceMind.backend.llm import claude as claude_mod
    importlib.reload(claude_mod)

    fake_mod, fake_cls = _make_fake_anthropic(text_response="world")

    # Patch where used: inside SourceMind.backend.llm.claude
    monkeypatch.setattr(claude_mod, "_get_anthropic", lambda: fake_cls)

    p = claude_mod.ClaudeProvider(model="claude-test")
    result = p.complete("say hi")
    assert result == "world"
    assert isinstance(result, str)


def test_claude_complete_schema(monkeypatch):
    import importlib
    from SourceMind.backend.llm import claude as claude_mod
    importlib.reload(claude_mod)

    expected_dict = {"value": 99}
    fake_mod, fake_cls = _make_fake_anthropic(tool_response=expected_dict)
    monkeypatch.setattr(claude_mod, "_get_anthropic", lambda: fake_cls)

    p = claude_mod.ClaudeProvider(model="claude-test")
    schema = {"type": "object", "properties": {"value": {"type": "integer"}}}
    result = p.complete("give me a number", schema=schema)
    assert result == expected_dict
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# OllamaProvider transport stubs
# ---------------------------------------------------------------------------

def test_ollama_complete_text(monkeypatch):
    import importlib
    from SourceMind.backend.llm import ollama as ollama_mod
    importlib.reload(ollama_mod)

    def fake_chat(**kwargs):
        return {"message": {"content": "ollama text"}}

    monkeypatch.setattr(ollama_mod, "_ollama_chat", fake_chat)

    p = ollama_mod.OllamaProvider(model="llama3.1")
    result = p.complete("hi")
    assert result == "ollama text"
    assert isinstance(result, str)


def test_ollama_complete_schema(monkeypatch):
    import importlib
    import json
    from SourceMind.backend.llm import ollama as ollama_mod
    importlib.reload(ollama_mod)

    expected = {"name": "Alice"}

    def fake_chat(**kwargs):
        return {"message": {"content": json.dumps(expected)}}

    monkeypatch.setattr(ollama_mod, "_ollama_chat", fake_chat)

    p = ollama_mod.OllamaProvider(model="llama3.1")
    schema = {"type": "object", "properties": {"name": {"type": "string"}}}
    result = p.complete("give me a name", schema=schema)
    assert result == expected
    assert isinstance(result, dict)


def test_ollama_complete_passes_max_tokens(monkeypatch):
    import importlib
    from SourceMind.backend.llm import ollama as ollama_mod
    importlib.reload(ollama_mod)

    captured = {}

    def fake_chat(**kwargs):
        captured.update(kwargs)
        return {"message": {"content": "ok"}}

    monkeypatch.setattr(ollama_mod, "_ollama_chat", fake_chat)

    p = ollama_mod.OllamaProvider(model="llama3.1")
    p.complete("hi", max_tokens=123)
    assert captured.get("options") == {"num_predict": 123}


def test_default_claude_model_reexported():
    from SourceMind.backend.llm import DEFAULT_CLAUDE_MODEL
    assert DEFAULT_CLAUDE_MODEL == "claude-sonnet-4-6"
