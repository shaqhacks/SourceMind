"""Cosine-similarity-based chunk retrieval from the SourceMind database."""
from __future__ import annotations

import math

from SourceMind.backend.db import models
from SourceMind.backend.llm.embed import embed_text  # module-level so tests can monkeypatch

try:
    import numpy as np
except ImportError:  # pragma: no cover - exercised only in numpy-less environments
    np = None


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


def _cosine_batch(query_embedding, embeddings: list) -> list[float]:
    """Score *query_embedding* against every vector in *embeddings* at once.

    Vectorized with numpy (one matrix-vector product) instead of a Python
    ``cosine()`` call per chunk, which matters once a course has thousands of
    chunks. Falls back to the pure-Python path per-chunk when numpy isn't
    installed, or when the embeddings can't be stacked into a rectangular
    matrix (e.g. ragged/corrupted dimensions) — same ranking semantics either
    way. Chunks with no embedding always score 0.0.
    """
    if np is None:
        return [cosine(query_embedding, e) if e else 0.0 for e in embeddings]

    dims = len(query_embedding)
    try:
        matrix = np.asarray(
            [e if e else [0.0] * dims for e in embeddings],
            dtype=float,
        )
        qe = np.asarray(query_embedding, dtype=float)
        row_norms = np.linalg.norm(matrix, axis=1)
        q_norm = np.linalg.norm(qe)
        denom = row_norms * q_norm
        with np.errstate(invalid="ignore", divide="ignore"):
            scores = np.where(denom == 0.0, 0.0, (matrix @ qe) / denom)
        return [float(s) for s in scores]
    except ValueError:
        # Ragged/mismatched embedding dimensions — numpy can't stack them;
        # fall back to scoring each chunk independently.
        return [cosine(query_embedding, e) if e else 0.0 for e in embeddings]


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
    if not chunks:
        return []

    scores = _cosine_batch(qe, [c.embedding for c in chunks])
    scored = [
        {"source_ref": c.source_ref, "content": c.content, "score": score}
        for c, score in zip(chunks, scores)
    ]
    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:k]
