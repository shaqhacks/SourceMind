from __future__ import annotations

from typing import Any

from sqlalchemy import func

from app.db.engine import get_session
from app.db.models import LlmCall


def get_usage(course_id: str | None) -> dict[str, Any]:
    session = get_session()
    try:
        query = session.query(
            func.count(LlmCall.id),
            func.coalesce(func.sum(LlmCall.input_tokens), 0),
            func.coalesce(func.sum(LlmCall.output_tokens), 0),
            func.coalesce(func.sum(LlmCall.cost_estimate), 0.0),
        )
        if course_id is not None:
            query = query.filter(LlmCall.course_id == course_id)
        calls, input_tokens, output_tokens, est_cost_usd = query.one()
        return {
            "calls": calls,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "est_cost_usd": est_cost_usd,
        }
    finally:
        session.close()
