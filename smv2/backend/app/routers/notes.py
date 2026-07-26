from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import NoteIn, NoteOut, NoteUpdateIn
from app.services import courses_service, notes_service

# Course-scoped list/create.
router = APIRouter(prefix="/api/courses", tags=["notes"])

# Item ops get their own top-level prefix — note ids are globally unique
# UUIDs, same pattern as highlights.highlight_router.
note_router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("/{course_id}/notes", operation_id="list_notes", response_model=list[NoteOut])
def list_notes(course_id: str) -> list[NoteOut]:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return [NoteOut.model_validate(n) for n in notes_service.list_notes(course_id)]


@router.post(
    "/{course_id}/notes", operation_id="create_note", response_model=NoteOut, status_code=201
)
def create_note(course_id: str, body: NoteIn) -> NoteOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    try:
        result = notes_service.create_note(
            course_id,
            section_id=body.section_id,
            page=body.page,
            anchor_y=body.anchor_y,
            note_md=body.note_md,
            surface=body.surface,
        )
    except notes_service.InvalidSectionForCourseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return NoteOut.model_validate(result)


@note_router.patch("/{note_id}", operation_id="update_note", response_model=NoteOut)
def update_note(note_id: str, body: NoteUpdateIn) -> NoteOut:
    result = notes_service.update_note(note_id, body.model_dump(exclude_unset=True))
    if result is None:
        raise HTTPException(status_code=404, detail="note not found")
    return NoteOut.model_validate(result)


@note_router.delete("/{note_id}", operation_id="delete_note", status_code=204)
def delete_note(note_id: str) -> None:
    if not notes_service.delete_note(note_id):
        raise HTTPException(status_code=404, detail="note not found")
