"""Positional margin notes (surface="pdf"): a note anchored to a page + a
0..1 vertical fraction (anchor_y), independent of selected text. Page crosses
1-based (API) <-> 0-based (DB) through to_display_page, the same single
conversion rule as highlights_service.
"""

from __future__ import annotations

from typing import Any

from app.db.engine import get_session
from app.db.models import Note, Section, utcnow
from app.services import search_index
from app.services.sections_service import to_display_page


class InvalidSectionForCourseError(ValueError):
    pass


def _to_dict(n: Note) -> dict[str, Any]:
    return {
        "id": n.id,
        "course_id": n.course_id,
        "section_id": n.section_id,
        "surface": n.surface,
        "page": to_display_page(n.page),
        "anchor_y": n.anchor_y,
        "note_md": n.note_md,
        "created_at": n.created_at,
        "updated_at": n.updated_at,
    }


def list_notes(course_id: str) -> list[dict[str, Any]]:
    session = get_session()
    try:
        rows = (
            session.query(Note)
            .join(Section, Section.id == Note.section_id)
            .filter(Note.course_id == course_id)
            .order_by(Section.order_index, Note.created_at)
            .all()
        )
        return [_to_dict(n) for n in rows]
    finally:
        session.close()


def create_note(
    course_id: str,
    *,
    section_id: str,
    page: int,
    anchor_y: float,
    note_md: str,
    surface: str,
) -> dict[str, Any]:
    session = get_session()
    try:
        section = session.get(Section, section_id)
        if section is None or section.course_id != course_id:
            raise InvalidSectionForCourseError(
                f"section {section_id} does not belong to course {course_id}"
            )
        n = Note(
            course_id=course_id,
            section_id=section_id,
            surface=surface,
            page=page - 1,
            anchor_y=anchor_y,
            note_md=note_md,
        )
        session.add(n)
        session.flush()
        search_index.upsert_note_document(session, n)
        session.commit()
        return _to_dict(n)
    finally:
        session.close()


def update_note(note_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    """fields comes from NoteUpdateIn.model_dump(exclude_unset=True): absent
    key = leave alone; an explicit null note_md is a no-op, NOT a clear —
    unlike Highlight.note_md (nullable, so an explicit null there really does
    clear it), Note.note_md is NOT NULL at the DB level, so there is no
    'cleared' state to set it to. A note with nothing left to say should be
    deleted (see delete_note), not patched to a null body.
    """
    session = get_session()
    try:
        n = session.get(Note, note_id)
        if n is None:
            return None
        if "note_md" in fields and fields["note_md"] is not None:
            n.note_md = fields["note_md"]
        n.updated_at = utcnow()
        search_index.upsert_note_document(session, n)
        session.commit()
        return _to_dict(n)
    finally:
        session.close()


def delete_note(note_id: str) -> bool:
    session = get_session()
    try:
        n = session.get(Note, note_id)
        if n is None:
            return False
        search_index.delete_note_document(session, note_id)
        session.delete(n)
        session.commit()
        return True
    finally:
        session.close()
