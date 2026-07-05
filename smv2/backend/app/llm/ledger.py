"""Append-only spend/usage ledger — every provider call writes exactly one
row here, success or failure, so cost visibility can never be skipped by a
call path that forgets to log it (see app/llm/provider.py's wrapper).
"""

from __future__ import annotations

from sqlalchemy import func

from app.db.engine import get_session
from app.db.models import LlmCall, utcnow


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
