"""Append-only spend/usage ledger — every provider call writes exactly one
row here, success or failure, so cost visibility can never be skipped by a
call path that forgets to log it (see app/llm/provider.py's wrapper).
"""

from __future__ import annotations

from sqlalchemy import func

from app.config import course_spend_cap_usd
from app.db.engine import get_session
from app.db.models import LlmCall, utcnow


class SpendCapExceededError(Exception):
    pass


def record_llm_call(
    *,
    purpose: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
    cost_estimate: float | None,
    prompt_version: str | None,
    status: str,
    course_id: str | None,
) -> None:
    session = get_session()
    try:
        session.add(
            LlmCall(
                ts=utcnow(),
                purpose=purpose,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                cost_estimate=cost_estimate,
                prompt_version=prompt_version,
                status=status,
                course_id=course_id,
            )
        )
        session.commit()
    finally:
        session.close()


def course_spend_so_far(course_id: str) -> float:
    session = get_session()
    try:
        total = (
            session.query(func.sum(LlmCall.cost_estimate))
            .filter(LlmCall.course_id == course_id)
            .scalar()
        )
        return total or 0.0
    finally:
        session.close()


def ensure_spend_cap(course_id: str) -> None:
    """Raises SpendCapExceededError if course_id has already spent at or
    beyond its configured cap (course_spend_cap_usd(), None = uncapped).

    Call this immediately before every provider.complete()/embed() call that
    should respect the cap, with no yield points (DB commits, file/network
    I/O) in between the check and the call — a safety net bounded by
    llm_max_concurrency() overshoot, not exact billing enforcement (see
    ADR-006). Shared by every generation path (lesson, cards, quiz, chat) so
    the cap can't quietly apply to only one of them.
    """
    cap = course_spend_cap_usd()
    if cap is not None and course_spend_so_far(course_id) >= cap:
        raise SpendCapExceededError("course spend cap exceeded")
