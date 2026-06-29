"""Cosine-similarity-based chunk retrieval from the SourceMind database."""
from __future__ import annotations

import math

from SourceMind.backend.db import models
from SourceMind.backend.llm.embed import embed_text  # module-level so tests can monkeypatch


def cosine(a, b) -> float:
    """Pure-Python cosine similarity.

    Returns 0.0 when either input vector has zero norm.
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def retrieve(
    session,
    course_id: str,
    query: str,
    k: int = 6,
    query_embedding=None,
) -> list[dict]:
    """Return the top-k chunks most similar to *query* for *course_id*.

    Args:
        session: active SQLAlchemy session.
        course_id: filter chunks to this course.
        query: natural-language query text (only embedded when query_embedding is None).
        k: maximum number of results.
        query_embedding: pre-computed embedding list; when provided, embed_text
            is never called (useful for network-free unit tests).

    Returns:
        list of dicts with keys ``source_ref``, ``content``, ``score``,
        sorted in descending order of cosine similarity. Returns ``[]`` when
        the course has no chunks.
    """
    qe = query_embedding if query_embedding is not None else embed_text(query)
    chunks = session.query(models.Chunk).filter_by(course_id=course_id).all()
    scored = [
        {"source_ref": c.source_ref, "content": c.content, "score": cosine(qe, c.embedding) if c.embedding else 0.0}
        for c in chunks
    ]
    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:k]
