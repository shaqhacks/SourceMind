"""Embedding pipeline: embeds every chunk of a course whose embedding is
still NULL, one provider call for the whole batch (each provider handles
its own per-item isolation internally — see OllamaProvider._embed_impl).
If the configured provider has no embeddings API at all
(AnthropicProvider), every chunk simply stays null; retrieval degrades to
lexical-only in that case (see app/pipeline/retrieval.py).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Chunk, Job
from app.llm.provider import NotSupportedError, get_provider


def run_embed_course(session: Session, job: Job, course_id: str) -> dict[str, Any]:
    chunks = (
        session.query(Chunk)
        .filter(Chunk.course_id == course_id, Chunk.embedding.is_(None))
        .all()
    )
    if not chunks:
        return {"embedded": 0, "skipped": 0}

    job.progress = {"stage": "embedding", "pct": 10, "message": f"embedding {len(chunks)} chunks"}
    session.commit()

    provider = get_provider()
    try:
        embeddings = provider.embed([c.text for c in chunks], course_id=course_id)
    except NotSupportedError:
        # This provider has no embeddings API at all — every chunk stays
        # null; nothing more to do here.
        return {
            "embedded": 0,
            "skipped": len(chunks),
            "note": "provider does not support embeddings",
        }

    embedded_count = 0
    for chunk, embedding in zip(chunks, embeddings):
        if embedding is not None:
            chunk.embedding = embedding
            embedded_count += 1

    job.progress = {
        "stage": "done",
        "pct": 100,
        "message": f"embedded {embedded_count}/{len(chunks)} chunks",
    }
    session.commit()

    return {"embedded": embedded_count, "skipped": len(chunks) - embedded_count}
