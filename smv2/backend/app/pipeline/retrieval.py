"""Chunk retrieval for RAG chat: a hybrid of cosine similarity over chunk
embeddings and a deterministic lexical (token-overlap) score. Framework-
free — no fastapi. rank_chunks() touches the DB and the LLM provider (to
embed the query); _score_chunks() is the pure ranking logic underneath it,
kept separate so it's testable without either.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

import numpy as np
from sqlalchemy.orm import Session

from app.db.models import Chunk
from app.llm.provider import get_provider

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_VECTOR_WEIGHT = 0.5
_LEXICAL_WEIGHT = 0.5


@dataclass
class RankedChunk:
    chunk: Chunk
    score: float


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _lexical_score(query_tokens: Counter, chunk_tokens: Counter) -> float:
    """Deterministic token-overlap, TF-weighted, normalized to [0, 1]."""
    if not query_tokens or not chunk_tokens:
        return 0.0
    overlap = sum(min(query_tokens[t], chunk_tokens[t]) for t in query_tokens)
    total_query_tokens = sum(query_tokens.values())
    return overlap / total_query_tokens if total_query_tokens else 0.0


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        # Mismatched dimensions (e.g. a chunk embedded under a different
        # embedding model than the current query) — degrade this one chunk
        # to lexical-only rather than raising np.dot's ValueError and
        # failing the whole ranking.
        return 0.0
    a_arr = np.asarray(a, dtype=float)
    b_arr = np.asarray(b, dtype=float)
    denom = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    if denom == 0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / denom)


def score_chunks(
    chunks: list[Chunk], query: str, query_embedding: list[float] | None, k: int = 6
) -> list[RankedChunk]:
    """Pure ranking: NULL chunk embeddings are always skipped in the vector
    path (they score 0 there via the lexical-only branch below, never a
    crash or a made-up similarity); if query_embedding is None entirely
    (embedding unavailable/unsupported), every chunk falls back to
    lexical-only scoring.
    """
    query_tokens = Counter(_tokenize(query))

    scored: list[RankedChunk] = []
    for chunk in chunks:
        lexical = _lexical_score(query_tokens, Counter(_tokenize(chunk.text)))

        if query_embedding is not None and chunk.embedding is not None:
            vector = _cosine_similarity(query_embedding, chunk.embedding)
            score = _VECTOR_WEIGHT * vector + _LEXICAL_WEIGHT * lexical
        else:
            score = lexical

        scored.append(RankedChunk(chunk=chunk, score=score))

    scored.sort(key=lambda rc: rc.score, reverse=True)
    return scored[:k]


def _try_embed_query(query: str) -> list[float] | None:
    """None on ANY failure (unsupported provider, network error, etc.) —
    retrieval always degrades to lexical-only rather than failing the chat
    turn over an embedding hiccup.
    """
    try:
        results = get_provider().embed([query])
        return results[0] if results else None
    except Exception:
        return None


def rank_chunks(session: Session, course_id: str, query: str, k: int = 6) -> list[RankedChunk]:
    chunks = session.query(Chunk).filter(Chunk.course_id == course_id).all()
    if not chunks:
        return []

    query_embedding = _try_embed_query(query)
    return score_chunks(chunks, query, query_embedding, k=k)
