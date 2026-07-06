"""Synchronous RAG chat — NOT a job. Retrieves top-k chunks, makes ONE
bounded complete() call grounded in those excerpts, then deterministically
maps the model's [n] citation markers back to structured chunk references
(section_id/page/source_ref) so the frontend gets both a display string
and machine-usable citation data without ever having to parse source_ref
itself (source_ref is display-only, verbatim — nothing parses its format).
"""

from __future__ import annotations

import re
from typing import Any

from app.config import chat_history_turns, chat_top_k
from app.db.engine import get_session
from app.db.models import ChatTurn, Chunk, Course, Job
from app.llm.ledger import ensure_spend_cap
from app.llm.prompts import load_prompt
from app.llm.provider import ProviderTimeoutError, get_provider
from app.llm.retry import is_timeout
from app.pipeline.retrieval import rank_chunks
from app.services import jobs_service

_CITATION_RE = re.compile(r"\[(\d+)\]")
_MAX_TOKENS = 2048
_CHAT_HISTORY_LIMIT = 50


class CourseNotFoundError(ValueError):
    pass


def _has_any_embeddings(session, course_id: str) -> bool:
    return (
        session.query(Chunk)
        .filter(Chunk.course_id == course_id, Chunk.embedding.isnot(None))
        .first()
        is not None
    )


def _maybe_trigger_embed_course(session, course_id: str, provider) -> None:
    """Lazy, non-blocking: if this course has zero embedded chunks, enqueue
    an embed_course job (unless one is already in flight) so future chat
    turns get better retrieval — THIS turn still answers lexically.

    Skips entirely if the configured provider can't embed at all
    (AnthropicProvider) — otherwise every chat turn against a
    zero-embedding course would keep enqueueing a job doomed to no-op.
    """
    if not provider.supports_embeddings:
        return
    if _has_any_embeddings(session, course_id):
        return

    already_queued = (
        session.query(Job)
        .filter(Job.type == "embed_course", Job.status.in_(["queued", "running"]))
        .all()
    )
    if any((j.payload or {}).get("course_id") == course_id for j in already_queued):
        return

    jobs_service.create_job("embed_course", {"course_id": course_id})


def _build_excerpts_block(ranked) -> str:
    lines = [f"[{i}] (source: {rc.chunk.source_ref})\n{rc.chunk.text}" for i, rc in enumerate(ranked, start=1)]
    return "\n\n".join(lines)


def _build_history_messages(session, course_id: str, limit: int) -> list[dict]:
    """The last `limit` PRIOR turns as proper role messages, oldest first —
    prepended before the current turn's excerpts+question message so the
    model actually sees the conversation as multi-turn, matching what the
    UI already presents, instead of only ever the newest message in
    isolation.
    """
    if limit <= 0:
        return []
    turns = (
        session.query(ChatTurn)
        .filter(ChatTurn.course_id == course_id)
        .order_by(ChatTurn.created_at.desc())
        .limit(limit)
        .all()
    )
    return [{"role": t.role, "content": t.content} for t in reversed(turns)]


def send_chat(course_id: str, message: str) -> dict[str, Any]:
    session = get_session()
    try:
        course = session.get(Course, course_id)
        if course is None:
            raise CourseNotFoundError(f"course not found: {course_id}")

        provider = get_provider()
        _maybe_trigger_embed_course(session, course_id, provider)

        ranked = rank_chunks(session, course_id, message, k=chat_top_k())
        excerpts_block = _build_excerpts_block(ranked)

        system_prompt, prompt_version = load_prompt("chat")
        history_messages = _build_history_messages(session, course_id, chat_history_turns())
        user_content = f"<excerpts>\n{excerpts_block}\n</excerpts>\n\n<question>\n{message}\n</question>"
        messages = [*history_messages, {"role": "user", "content": user_content}]

        # Same cap discipline as generation (app/llm/ledger.ensure_spend_cap):
        # checked immediately before the call, no yield points in between.
        # Raises SpendCapExceededError, which the router maps to a 429
        # distinct from the busy-limiter one.
        ensure_spend_cap(course_id)

        # Persist NEITHER turn until the provider call actually succeeds —
        # committing the user turn early would leave it orphaned (with no
        # matching assistant reply) every time the provider errors or times
        # out, corrupting the transcript. Both rows land together in one
        # commit, only on success.
        try:
            result = provider.complete(
                messages,
                max_tokens=_MAX_TOKENS,
                purpose="chat",
                course_id=course_id,
                prompt_version=prompt_version,
                system=system_prompt,
            )
        except Exception as exc:
            if is_timeout(exc):
                raise ProviderTimeoutError("the LLM provider timed out; please try again") from exc
            raise

        cited_numbers = sorted({int(m) for m in _CITATION_RE.findall(result.text)})
        citations = [
            {
                "n": n,
                "section_id": ranked[n - 1].chunk.section_id,
                "page": ranked[n - 1].chunk.page,
                "source_ref": ranked[n - 1].chunk.source_ref,
            }
            for n in cited_numbers
            if 1 <= n <= len(ranked)
        ]

        session.add(ChatTurn(course_id=course_id, role="user", content=message))
        session.add(
            ChatTurn(course_id=course_id, role="assistant", content=result.text, citations=citations)
        )
        session.commit()

        return {"reply_md": result.text, "citations": citations}
    finally:
        session.close()


def get_chat_history(course_id: str, limit: int = _CHAT_HISTORY_LIMIT) -> list[ChatTurn]:
    """Returns the LATEST `limit` turns, in chronological order. Querying
    ASC+limit would freeze the transcript at the first `limit` turns
    forever (new turns past that point would never be returned) — DESC+
    limit picks the newest ones, then we reverse back to chronological
    order for display.
    """
    session = get_session()
    try:
        turns = (
            session.query(ChatTurn)
            .filter(ChatTurn.course_id == course_id)
            .order_by(ChatTurn.created_at.desc())
            .limit(limit)
            .all()
        )
        return list(reversed(turns))
    finally:
        session.close()
