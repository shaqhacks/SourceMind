"""Quiz generation pipeline: ONE bounded LLM call over a SCOPED set of
sections — capped combined input (~24k chars), each contributing a
proportional head if the total would exceed that cap so every selected
section is represented, never a whole-book call beyond that bound.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Course, Job, Section, Test, TestAttempt
from app.llm.ledger import ensure_spend_cap, record_llm_call
from app.llm.prompts import load_prompt
from app.llm.provider import get_provider
from app.pipeline._common import report_progress as _report_progress
from app.pipeline._common import report_progress_in_session as _report_progress_in_session
from app.pipeline._common import strip_leading_fence as _strip_leading_fence

logger = logging.getLogger(__name__)

_MAX_TOKENS = 4096
_MAX_COMBINED_CHARS = 24_000
_QUESTION_COUNT = 8


def _build_scoped_text(sections: list[Section]) -> str:
    """Combines sections' body_md into one blob capped at
    _MAX_COMBINED_CHARS. If the total exceeds the cap, each section
    contributes a proportional head rather than just including the first
    few sections in full and dropping the rest — every selected section is
    represented, even if truncated.
    """
    bodies = [s.body_md or "" for s in sections]
    total_len = sum(len(b) for b in bodies)

    if total_len <= _MAX_COMBINED_CHARS or total_len == 0:
        heads = bodies
    else:
        heads = [b[: int(_MAX_COMBINED_CHARS * (len(b) / total_len))] for b in bodies]

    parts = [f"## {s.title}\n\n{head}" for s, head in zip(sections, heads)]
    return "\n\n---\n\n".join(parts)


def _parse_questions(text: str) -> list[dict[str, Any]]:
    data = json.loads(_strip_leading_fence(text))
    if not isinstance(data, list):
        raise ValueError("expected a JSON array of questions")

    questions: list[dict[str, Any]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            logger.warning("dropping malformed question item %d: not an object", i)
            continue
        question = item.get("question")
        choices = item.get("choices")
        correct_index = item.get("correct_index")
        explanation = item.get("explanation")

        if not isinstance(question, str) or not question.strip():
            logger.warning("dropping malformed question item %d: missing question", i)
            continue
        if not isinstance(choices, list) or len(choices) != 4 or not all(
            isinstance(c, str) and c.strip() for c in choices
        ):
            logger.warning("dropping malformed question item %d: choices must be 4 non-empty strings", i)
            continue
        if not isinstance(correct_index, int) or isinstance(correct_index, bool) or not (0 <= correct_index < 4):
            logger.warning("dropping malformed question item %d: correct_index out of range", i)
            continue
        if not isinstance(explanation, str):
            explanation = ""

        questions.append(
            {
                "question": question.strip(),
                "choices": [c.strip() for c in choices],
                "correct_index": correct_index,
                "explanation": explanation.strip(),
            }
        )

    return questions


def run_test_generation(
    session: Session,
    job: Job,
    course_id: str,
    section_ids: list[str] | None,
    chapter_label: str | None = None,
) -> dict[str, Any]:
    course = session.get(Course, course_id)
    if course is None:
        raise ValueError(f"course not found: {course_id}")

    query = session.query(Section).filter(Section.course_id == course_id)
    if section_ids:
        # Explicit scope (caller-chosen sections, including chapter_label's
        # own resolution in tests_service.py, which already excludes
        # answer-key sections itself) — honored as-is, unchanged from before.
        query = query.filter(Section.id.in_(section_ids))
    else:
        # Whole-course fallback: the system, not the caller, is choosing
        # scope here, so a printed answer key must never end up in the
        # prompt — same reasoning chapter_label resolution uses.
        query = query.filter(Section.kind != "answers")
    sections = query.order_by(Section.order_index).all()

    if not sections:
        raise ValueError("no sections available to build a test from")

    _report_progress(job.id, stage="generating", pct=10, message="generating quiz")

    scoped_text = _build_scoped_text(sections)
    system_prompt, prompt_version = load_prompt("quiz")
    messages = [{"role": "user", "content": f"<source_text>\n{scoped_text}\n</source_text>"}]

    provider = get_provider()

    # Same cap discipline as lesson generation (app/llm/ledger.ensure_spend_cap):
    # checked immediately before the call, no yield points in between.
    ensure_spend_cap(course_id)

    # wait_for_slot=True: durable job, not an interactive request — wait out
    # a busy limiter (bounded) rather than fail the job over transient chat
    # traffic saturating the same slots.
    result = provider.complete(
        messages,
        max_tokens=_MAX_TOKENS,
        purpose="quiz",
        course_id=course_id,
        prompt_version=prompt_version,
        system=system_prompt,
        wait_for_slot=True,
    )

    try:
        questions = _parse_questions(result.text)
    except (json.JSONDecodeError, ValueError):
        _report_progress(job.id, stage="retrying", pct=50, message="retrying malformed response")
        result = provider.complete(
            messages,
            max_tokens=_MAX_TOKENS,
            purpose="quiz",
            course_id=course_id,
            prompt_version=prompt_version,
            system=system_prompt,
            wait_for_slot=True,
        )
        try:
            questions = _parse_questions(result.text)
        except (json.JSONDecodeError, ValueError) as exc:
            # The provider wrapper already recorded this same call as
            # status='ok' (the completion succeeded at the transport level);
            # this is the semantic layer recording that its CONTENT was
            # unusable. cost_estimate stays None — that spend was already
            # counted by the 'ok' row, and double-recording it here would
            # double-count against course_spend_so_far().
            record_llm_call(
                purpose="quiz",
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                latency_ms=0,
                cost_estimate=None,
                prompt_version=prompt_version,
                status="parse_failure",
                course_id=course_id,
            )
            raise ValueError(f"quiz generation produced unparseable output after one retry: {exc}") from exc

    if not questions:
        raise ValueError("quiz generation produced zero usable questions")

    questions = questions[:_QUESTION_COUNT]
    # ADR-022 deck/attempt split: Test is the persisted deck (questions,
    # generated once); TestAttempt is just this first attempt against it.
    # Retaking (tests_service.retake_test) creates further TestAttempts
    # against this SAME Test, zero further LLM calls.
    test = Test(
        course_id=course_id,
        section_id=section_ids[0] if section_ids and len(section_ids) == 1 else None,
        chapter_label=chapter_label,
        questions=questions,
        prompt_version=prompt_version,
        model=result.model,
    )
    session.add(test)
    session.flush()  # test.id must exist before the attempt references it
    attempt = TestAttempt(test_id=test.id, course_id=course_id)
    session.add(attempt)
    # In-session (not report_progress): the Test/TestAttempt inserts above
    # are already pending on this session — see report_progress_in_session's
    # docstring.
    _report_progress_in_session(job, stage="done", pct=100, message="quiz ready")
    session.commit()

    return {"test_id": test.id, "attempt_id": attempt.id, "question_count": len(questions)}
