"""Highlights: user-created text-quote annotations on a section's source
text (ADR-024). The anchor (exact/prefix/suffix/occurrence) is stored
opaquely — the frontend matcher owns its semantics. Page numbers cross
this boundary 1-based (API) <-> 0-based (DB), the same single-conversion
rule as sections_service.
"""

from __future__ import annotations

from typing import Any

from app.db.engine import get_session
from app.db.models import Highlight, Section, utcnow
from app.services.sections_service import to_display_page


class InvalidSectionForCourseError(ValueError):
    pass


def _to_dict(h: Highlight) -> dict[str, Any]:
    return {
        "id": h.id,
        "course_id": h.course_id,
        "section_id": h.section_id,
        "exact": h.exact,
        "prefix": h.prefix,
        "suffix": h.suffix,
        "occurrence": h.occurrence,
        "page": to_display_page(h.page),
        "color": h.color,
        "surface": h.surface,
        "note_md": h.note_md,
        "created_at": h.created_at,
        "updated_at": h.updated_at,
    }


def list_highlights(course_id: str) -> list[dict[str, Any]]:
    session = get_session()
    try:
        rows = (
            session.query(Highlight)
            .join(Section, Section.id == Highlight.section_id)
            .filter(Highlight.course_id == course_id)
            .order_by(Section.order_index, Highlight.created_at)
            .all()
        )
        return [_to_dict(h) for h in rows]
    finally:
        session.close()


def create_highlight(
    course_id: str,
    *,
    section_id: str,
    exact: str,
    prefix: str,
    suffix: str,
    occurrence: int,
    page: int | None,
    color: str,
    surface: str,
) -> dict[str, Any]:
    session = get_session()
    try:
        section = session.get(Section, section_id)
        if section is None or section.course_id != course_id:
            raise InvalidSectionForCourseError(
                f"section {section_id} does not belong to course {course_id}"
            )
        h = Highlight(
            course_id=course_id,
            section_id=section_id,
            exact=exact,
            prefix=prefix,
            suffix=suffix,
            occurrence=occurrence,
            page=page - 1 if page is not None else None,
            color=color,
            surface=surface,
        )
        session.add(h)
        session.commit()
        return _to_dict(h)
    finally:
        session.close()


def update_highlight(highlight_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    """fields comes from HighlightUpdateIn.model_dump(exclude_unset=True):
    absent key = leave alone; note_md explicitly null = clear the note. A
    null color is a no-op (there is no 'no color' state to reset to).
    """
    session = get_session()
    try:
        h = session.get(Highlight, highlight_id)
        if h is None:
            return None
        if "note_md" in fields:
            h.note_md = fields["note_md"]
        if fields.get("color") is not None:
            h.color = fields["color"]
        h.updated_at = utcnow()
        session.commit()
        return _to_dict(h)
    finally:
        session.close()


def delete_highlight(highlight_id: str) -> bool:
    session = get_session()
    try:
        h = session.get(Highlight, highlight_id)
        if h is None:
            return False
        session.delete(h)
        session.commit()
        return True
    finally:
        session.close()
