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
from app.db.models import Card, ChatTurn, Chunk, Course, Job, ReviewState, Section, utcnow
from app.llm.ledger import ensure_spend_cap
from app.llm.prompts import load_prompt
from app.llm.provider import ProviderTimeoutError, get_provider
from app.llm.retry import is_timeout
from app.pipeline.retrieval import rank_chunks
from app.services import chapters_service, jobs_service
from app.services.study_service import study_next

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


def _distinct_chapter_labels_hit(session, ranked) -> list[str]:
    """Chapter labels for the sections THIS TURN's retrieval actually hit,
    deduped, in first-seen (i.e. highest-ranked-first) order — never the
    whole course, only what's relevant to this specific question.
    """
    section_ids = [rc.chunk.section_id for rc in ranked]
    if not section_ids:
        return []
    label_by_section = dict(
        session.query(Section.id, Section.chapter_label).filter(Section.id.in_(section_ids)).all()
    )
    labels: list[str] = []
    seen: set[str] = set()
    for rc in ranked:
        label = label_by_section.get(rc.chunk.section_id)
        if label is not None and label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def _due_and_lapsed_card_counts(session, section_ids: list[str], now) -> tuple[int, int]:
    if not section_ids:
        return 0, 0
    due_count = (
        session.query(Card)
        .outerjoin(ReviewState, ReviewState.card_id == Card.id)
        .filter(Card.section_id.in_(section_ids))
        .filter((ReviewState.due_at.is_(None)) | (ReviewState.due_at <= now))
        .count()
    )
    lapsed_count = (
        session.query(Card)
        .join(ReviewState, ReviewState.card_id == Card.id)
        .filter(Card.section_id.in_(section_ids), ReviewState.lapses > 0)
        .count()
    )
    return due_count, lapsed_count


def _build_learner_state_block(session, course_id: str, ranked) -> str:
    """Deterministic learner-state lines for the chapters this turn's
    retrieval hit — chapter test best/latest scores, due+lapsed card
    counts, whether a lesson exists — one line per chapter, values
    straight from SQL/chapters_service. The model never computes any of
    this itself (the v3 chat prompt's rule); this function is the ONLY
    place these numbers are produced.
    """
    labels = _distinct_chapter_labels_hit(session, ranked)
    if not labels:
        return ""

    chapters_by_label = {c["chapter_label"]: c for c in chapters_service.get_chapters(course_id)}
    now = utcnow()
    lines = []
    for label in labels:
        chapter = chapters_by_label.get(label)
        if chapter is None:
            continue
        stats = chapter["test_stats"]
        if stats is None:
            score_part = "no test attempts yet"
        elif stats["best_score"] is None:
            score_part = "test attempted, not yet graded"
        else:
            score_part = (
                f"best test score {stats['best_score'] * 100:.0f}%, "
                f"latest {stats['latest_score'] * 100:.0f}%"
            )

        content_section_ids = chapter["section_ids"]
        all_section_ids = content_section_ids + chapter["practice_section_ids"]
        due_count, lapsed_count = _due_and_lapsed_card_counts(session, all_section_ids, now)

        lesson_ready = False
        if content_section_ids:
            lesson_ready = (
                session.query(Section)
                .filter(Section.id.in_(content_section_ids), Section.lesson_status == "ready")
                .first()
                is not None
            )
        lesson_part = "lesson generated" if lesson_ready else "no lesson generated yet"

        lines.append(f"{label} — {score_part}, cards due {due_count}, cards lapsed {lapsed_count}, {lesson_part}")
    return "\n".join(lines)


def _build_study_suggestions_block(course_id: str) -> str:
    """Top-3 deterministic study suggestions (app.services.study_service),
    formatted as plain lines for the chat prompt's "the app suggests"
    block — the v3 prompt may weave ONE of these into its closing line,
    never fabricate its own.
    """
    suggestions = study_next(course_id, limit=3)
    if not suggestions:
        return ""

    lines = []
    for s in suggestions:
        label = s["chapter_label"] or "Front matter"
        reason, detail = s["reason"], s["detail"]
        if reason == "low_test_score":
            lines.append(f"- {label}: best test score {detail['best_score'] * 100:.0f}% — could use review")
        elif reason == "due_cards":
            lines.append(f"- {label}: {detail['due_count']} flashcards due for review")
        elif reason == "unread":
            lines.append(f"- {label}: not started yet")
        else:  # stale
            lines.append(f"- {label}: not revisited in {detail['days_since']} day(s)")
    return "\n".join(lines)


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
        # ADR-022 learning-companion context: deterministic, DB-computed —
        # never left to the model to estimate. learner_state is scoped to
        # only the chapters THIS turn's retrieval hit; study_suggestions is
        # course-wide (independent of what was asked this turn).
        learner_state_block = _build_learner_state_block(session, course_id, ranked)
        study_suggestions_block = _build_study_suggestions_block(course_id)

        system_prompt, prompt_version = load_prompt("chat")
        history_messages = _build_history_messages(session, course_id, chat_history_turns())
        user_parts = [f"<excerpts>\n{excerpts_block}\n</excerpts>"]
        if learner_state_block:
            user_parts.append(f"<learner_state>\n{learner_state_block}\n</learner_state>")
        if study_suggestions_block:
            user_parts.append(f"<study_suggestions>\n{study_suggestions_block}\n</study_suggestions>")
        user_parts.append(f"<question>\n{message}\n</question>")
        user_content = "\n\n".join(user_parts)
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
