from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import HighlightIn, HighlightOut, HighlightUpdateIn
from app.services import courses_service, highlights_service

# Course-scoped list/create.
router = APIRouter(prefix="/api/courses", tags=["highlights"])

# Item ops get their own top-level prefix — highlight ids are globally
# unique UUIDs, same pattern as sections.section_router.
highlight_router = APIRouter(prefix="/api/highlights", tags=["highlights"])


@router.get(
    "/{course_id}/highlights", operation_id="list_highlights", response_model=list[HighlightOut]
)
def list_highlights(course_id: str) -> list[HighlightOut]:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return [HighlightOut.model_validate(h) for h in highlights_service.list_highlights(course_id)]


@router.post(
    "/{course_id}/highlights",
    operation_id="create_highlight",
    response_model=HighlightOut,
    status_code=201,
)
def create_highlight(course_id: str, body: HighlightIn) -> HighlightOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    try:
        result = highlights_service.create_highlight(
            course_id,
            section_id=body.section_id,
            exact=body.exact,
            prefix=body.prefix,
            suffix=body.suffix,
            occurrence=body.occurrence,
            page=body.page,
            color=body.color,
            surface=body.surface,
        )
    except highlights_service.InvalidSectionForCourseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return HighlightOut.model_validate(result)


@highlight_router.patch(
    "/{highlight_id}", operation_id="update_highlight", response_model=HighlightOut
)
def update_highlight(highlight_id: str, body: HighlightUpdateIn) -> HighlightOut:
    result = highlights_service.update_highlight(highlight_id, body.model_dump(exclude_unset=True))
    if result is None:
        raise HTTPException(status_code=404, detail="highlight not found")
    return HighlightOut.model_validate(result)


@highlight_router.delete("/{highlight_id}", operation_id="delete_highlight", status_code=204)
def delete_highlight(highlight_id: str) -> None:
    if not highlights_service.delete_highlight(highlight_id):
        raise HTTPException(status_code=404, detail="highlight not found")
