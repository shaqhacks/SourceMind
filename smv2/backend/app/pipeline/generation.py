"""Lesson generation pipeline: exactly ONE bounded LLM call per section,
scoped to that section's own body_md only — never a whole-book call
(ADR-010's zero-LLM ingest stays untouched; this module is what generation
looks like once a human explicitly asks for it, lazily, one section at a
time).

This is the ONLY place lesson_md is ever written. body_md is never touched
here — the ORM 'set' guard on Section.body_md (app/db/models.py) would
raise immediately if it were.

Degenerate output (empty/whitespace-only) gets exactly ONE retry — a
second bad result fails the section outright rather than looping.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import course_spend_cap_usd
from app.db.models import Job, Section
from app.llm.ledger import SpendCapExceededError, course_spend_so_far, ensure_spend_cap, record_llm_call
from app.llm.prompts import load_prompt
from app.llm.provider import get_provider
from app.pipeline._common import report_progress as _report_progress
from app.pipeline._common import report_progress_in_session as _report_progress_in_session
from app.pipeline._common import strip_leading_fence as _strip_leading_fence
from app.services import search_index

_MAX_TOKENS = 4096


def _is_degenerate(text: str) -> bool:
    return not text or not text.strip()


def _build_messages(section: Section) -> tuple[str, list[dict]]:
    """Returns (system_prompt, messages).

    The instructions live entirely in the system prompt; the user message
    contains ONLY the chapter title and the source text, wrapped in
    <source_text> tags. body_md came from an uploaded PDF — untrusted
    content — so it must never share a message with the instructions
    (prompt-injection guard); the prompt itself also tells the model to
    treat <source_text> strictly as material to teach, never as commands.
    """
    system_prompt, _ = load_prompt("lesson")
    user_content = f"Chapter title: {section.title}\n\n<source_text>\n{section.body_md}\n</source_text>"
    return system_prompt, [{"role": "user", "content": user_content}]


def run_lesson_generation(session: Session, job: Job, section_id: str) -> dict[str, Any]:
    """Entry point: validates the section, then generates under a safety
    net that guarantees lesson_status never gets stuck on 'generating' —
    any unhandled exception marks it 'failed' before re-raising.
    """
    section = session.get(Section, section_id)
    if section is None:
        raise ValueError(f"section not found: {section_id}")

    section.lesson_status = "generating"
    session.commit()

    try:
        return _generate(session, job, section_id)
    except Exception:
        session.rollback()
        failed_section = session.get(Section, section_id)
        if failed_section is not None:
            failed_section.lesson_status = "failed"
            session.commit()
        raise


def _generate(session: Session, job: Job, section_id: str) -> dict[str, Any]:
    section = session.get(Section, section_id)
    assert section is not None  # already validated by run_lesson_generation

    _report_progress(job.id, stage="generating", pct=10, message=f"generating lesson for {section.title}")

    system_prompt, messages = _build_messages(section)
    _, prompt_version = load_prompt("lesson")
    provider = get_provider()

    # Spend-cap check happens immediately before the provider call itself,
    # with no yield points (DB commits, file/network I/O) in between. This
    # is a safety net, not exact billing enforcement: up to
    # llm_max_concurrency() calls could all pass this check before any of
    # them commits its ledger row, so a tight cap can still be overshot by
    # that many concurrent in-flight calls. The realistic overspend path
    # this guards is generate_all_lessons's batch of sequential jobs — the
    # single worker fully completes one job (including its ledger commit)
    # before claiming the next, so this check is airtight for that case.
    cap = course_spend_cap_usd()
    try:
        ensure_spend_cap(section.course_id)
    except SpendCapExceededError:
        section.lesson_status = "failed"
        session.commit()
        raise

    # wait_for_slot=True: this is a durable job, not an interactive request —
    # it should wait out a busy limiter (bounded) rather than fail the whole
    # job over transient chat traffic saturating the same slots.
    result = provider.complete(
        messages,
        max_tokens=_MAX_TOKENS,
        purpose="lesson",
        course_id=section.course_id,
        prompt_version=prompt_version,
        system=system_prompt,
        wait_for_slot=True,
    )
    text = _strip_leading_fence(result.text)

    if _is_degenerate(text):
        # Bounded: exactly one retry on degenerate output, then give up —
        # no "ask the model to fix it" loop.
        _report_progress(job.id, stage="retrying", pct=50, message="retrying degenerate output")
        result = provider.complete(
            messages,
            max_tokens=_MAX_TOKENS,
            purpose="lesson",
            course_id=section.course_id,
            prompt_version=prompt_version,
            system=system_prompt,
            wait_for_slot=True,
        )
        text = _strip_leading_fence(result.text)

    if _is_degenerate(text):
        section.lesson_status = "failed"
        session.commit()
        # The provider wrapper already recorded this same call as
        # status='ok' (the completion succeeded at the transport level);
        # this is the semantic layer recording that its CONTENT was unusable.
        # cost_estimate stays None — that spend was already counted by the
        # 'ok' row, and double-recording it here would double-count against
        # course_spend_so_far().
        record_llm_call(
            purpose="lesson",
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            latency_ms=0,
            cost_estimate=None,
            prompt_version=prompt_version,
            status="parse_failure",
            course_id=section.course_id,
        )
        raise ValueError("lesson generation produced degenerate output after one retry")

    section.lesson_md = text
    section.lesson_status = "ready"
    section.lesson_model = result.model
    section.lesson_prompt_version = prompt_version
    search_index.upsert_lesson_document(session, section)
    # In-session (not report_progress): the section fields above are already
    # pending on this session — see report_progress_in_session's docstring.
    _report_progress_in_session(job, stage="done", pct=100, message="lesson ready")
    session.commit()

    # Re-check after completion: THIS call may have just pushed spend over
    # the cap. A call already made can't be undone, but flagging it in the
    # job result lets a batch drain (generate_all_lessons) notice and stop
    # enqueuing further work for this course rather than only finding out
    # when the next job's own pre-call check fails.
    spend_cap_reached = cap is not None and course_spend_so_far(section.course_id) >= cap
    return {"spend_cap_reached": spend_cap_reached}
