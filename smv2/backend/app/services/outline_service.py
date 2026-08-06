"""Thin wrapper around app.pipeline.outline: owns the session lifecycle,
converts pydantic operation models to the plain dicts the pipeline expects
(including the 1-based -> 0-based at_page conversion for split), and shapes
the resulting Sections the same way sections_service's list view does.
"""

from __future__ import annotations

from typing import Any

from app.db.engine import get_session
from app.pipeline.outline import OutlineOperationError, apply_operations
from app.services.sections_service import to_display_page

__all__ = ["OutlineOperationError", "edit_outline"]


def _op_to_dict(op: Any) -> dict[str, Any]:
    data = op.model_dump()
    if data.get("type") == "split":
        data["at_page"] = data["at_page"] - 1  # API is 1-based; pipeline is 0-based
    return data


def edit_outline(course_id: str, operations: list[Any]) -> list[dict[str, Any]]:
    session = get_session()
    try:
        op_dicts = [_op_to_dict(op) for op in operations]
        try:
            sections = apply_operations(session, course_id, op_dicts)
        except OutlineOperationError:
            session.rollback()
            raise

        return [
            {
                "id": s.id,
                "title": s.title,
                "order_index": s.order_index,
                "asset_id": s.asset_id,
                "page_start": to_display_page(s.page_start),
                "page_end": to_display_page(s.page_end),
                "source_format": s.source_format,
                "source_locator": s.source_locator,
                "lesson_status": s.lesson_status,
                "has_content": bool((s.body_md or "").strip()),
                "word_count": len((s.body_md or "").split()),
                "kind": s.kind,
                "chapter_label": s.chapter_label,
            }
            for s in sections
        ]
    finally:
        session.close()
