"""Local text embeddings via Ollama.

Mirrors the lazy-import + stubbable-helper pattern in ollama.py so tests can
patch ``_ollama_embed``/``_ollama_embed_batch`` without a real Ollama server
running.
"""
from __future__ import annotations

import os

from SourceMind.backend import config
from SourceMind.backend.llm._timeout import call_with_timeout_retry
from SourceMind.backend.llm.limiter import llm_slot


def _ollama_embed(model: str, prompt: str) -> list[float]:
    """Lazy-imported ollama.embeddings call (single input); patched in tests."""
    import ollama
    return ollama.embeddings(model=model, prompt=prompt)["embedding"]


def _ollama_embed_batch(model: str, prompts: list[str]) -> list[list[float]]:
    """Lazy-imported ollama.embed call (native batch ``input``); patched in tests."""
    import ollama
    return ollama.embed(model=model, input=prompts)["embeddings"]


def _model() -> str:
    return os.environ.get("SOURCEMIND_EMBED_MODEL", "nomic-embed-text")


def embed_text(text: str) -> list[float]:
    model = _model()
    with llm_slot():
        return call_with_timeout_retry(lambda: _ollama_embed(model, text))


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed many texts with as few round-trips as possible.

    Uses Ollama's native batch ``embed()`` endpoint (``input`` accepts a list)
    instead of one ``embeddings()`` call per text, splitting into batches of
    ``config.embed_batch_size()`` (default 64) so a single call doesn't send
    an unbounded request body for very large courses.
    """
    if not texts:
        return []
    model = _model()
    batch_size = config.embed_batch_size()
    out: list[list[float]] = []
    with llm_slot():
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            result = call_with_timeout_retry(lambda b=batch: _ollama_embed_batch(model, b))
            out.extend(result)
    return out
