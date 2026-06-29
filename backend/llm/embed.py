"""Local text embeddings via Ollama.

Mirrors the lazy-import + stubbable-helper pattern in ollama.py so tests can
patch ``_ollama_embed`` without a real Ollama server running.
"""
from __future__ import annotations

import os


def _ollama_embed(model: str, prompt: str) -> list[float]:
    """Lazy-imported ollama.embeddings call; patched in tests."""
    import ollama
    return ollama.embeddings(model=model, prompt=prompt)["embedding"]


def _model() -> str:
    return os.environ.get("SOURCEMIND_EMBED_MODEL", "nomic-embed-text")


def embed_text(text: str) -> list[float]:
    return _ollama_embed(_model(), text)


def embed_texts(texts: list[str]) -> list[list[float]]:
    return [_ollama_embed(_model(), t) for t in texts]
