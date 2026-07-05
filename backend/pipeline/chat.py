"""Chat orchestration — chapter-grounded and course-grounded Q&A.

Both entry points build a prompt from document-derived context (sanitized
against prompt-injection), call the provider, and persist the exchange as
ChatTurn rows. Callers (the library router) are responsible for validating
that the course/chapter exists before calling these — that is an HTTP-facing
404 concern, not business logic.
"""
from __future__ import annotations

from datetime import datetime, timezone

from SourceMind.backend.db import base, models
from SourceMind.backend.llm.provider import LLMProvider
from SourceMind.backend.pipeline.retrieve import retrieve
from SourceMind.backend.services.ingest.security import sanitize_source

# Sentinel section_id for course-level chat turns (no specific chapter).
COURSE_CHAT_SECTION = "__course__"


def run_chapter_chat(
    course_id: str,
    section_id: str,
    question: str,
    provider: LLMProvider,
) -> dict:
    """Answer *question* grounded in a chapter's content; persist the exchange.

    Assumes the caller already verified the course/chapter exist. Returns
    ``{"answer": str}``.
    """
    with base.get_session() as session:
        chapter = (
            session.query(models.Chapter)
            .filter_by(course_id=course_id, section_id=section_id)
            .first()
        )
        body_md = chapter.body_md if chapter else ""
        body_md = body_md or ""

    # Neutralize prompt-injection imperatives in the document-derived context
    # (NOT the user's question, which is legitimate user input).
    clean_body_md, _ = sanitize_source(body_md)

    prompt = (
        "You are a study assistant. Answer the question using ONLY the following "
        "chapter content. Do not introduce information not present in the chapter.\n\n"
        f"=== CHAPTER CONTENT ===\n{clean_body_md}\n\n"
        f"=== QUESTION ===\n{question}"
    )
    answer = provider.complete(prompt)
    if not isinstance(answer, str):
        answer = str(answer)

    now = datetime.now(timezone.utc).isoformat()
    with base.get_session() as session:
        session.add(models.ChatTurn(
            course_id=course_id,
            section_id=section_id,
            role="user",
            content=question,
            created_at=now,
        ))
        session.add(models.ChatTurn(
            course_id=course_id,
            section_id=section_id,
            role="assistant",
            content=answer,
            created_at=now,
        ))

    return {"answer": answer}


def run_course_chat(
    course_id: str,
    question: str,
    provider: LLMProvider,
) -> dict:
    """Answer *question* grounded in course chunks with citations; persist the exchange.

    Assumes the caller already verified the course exists. Returns
    ``{"answer": str, "citations": [...]}``.
    """
    with base.get_session() as session:
        results = retrieve(session, course_id, question, k=6)

    # Neutralize prompt-injection imperatives in retrieved (document-derived)
    # chunk content before it is injected as context for the model.
    for r in results:
        r["content"] = sanitize_source(r.get("content") or "")[0]

    citations = [{"source_ref": r["source_ref"], "content": r["content"]} for r in results]

    system = (
        "Answer ONLY from the numbered sources; cite sources as [1],[2]; "
        "if they don't contain the answer, say so."
    )
    sources_block = "\n".join(
        f"[{i}] ({r['source_ref']}): {r['content']}" for i, r in enumerate(results, 1)
    )
    prompt = f"Sources:\n{sources_block}\n\nQuestion: {question}"

    answer = provider.complete(prompt, system=system)
    if not isinstance(answer, str):
        answer = str(answer)

    now = datetime.now(timezone.utc).isoformat()
    with base.get_session() as session:
        session.add(models.ChatTurn(
            course_id=course_id,
            section_id=COURSE_CHAT_SECTION,
            role="user",
            content=question,
            citations=None,
            created_at=now,
        ))
        session.add(models.ChatTurn(
            course_id=course_id,
            section_id=COURSE_CHAT_SECTION,
            role="assistant",
            content=answer,
            citations=citations,
            created_at=now,
        ))

    return {"answer": answer, "citations": citations}
