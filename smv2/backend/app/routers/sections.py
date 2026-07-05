from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import ProgressIn, ProgressOut, SectionDetailOut, SectionOut
from app.services import courses_service, sections_service

# Course-scoped reader endpoints (list, progress).
router = APIRouter(prefix="/api/courses", tags=["sections"])

# Section detail is not course-scoped in the URL — section ids are globally
# unique (content-addressed), so it gets its own top-level prefix.
section_router = APIRouter(prefix="/api/sections", tags=["sections"])


@router.get("/{course_id}/sections", operation_id="list_sections", response_model=list[SectionOut])
def list_sections(course_id: str) -> list[SectionOut]:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return [SectionOut.model_validate(s) for s in sections_service.list_sections(course_id)]


@section_router.get("/{section_id}", operation_id="get_section", response_model=SectionDetailOut)
def get_section(section_id: str) -> SectionDetailOut:
    section = sections_service.get_section(section_id)
    if section is None:
        raise HTTPException(status_code=404, detail="section not found")
    return SectionDetailOut.model_validate(section)


@router.put("/{course_id}/progress", operation_id="save_progress", response_model=ProgressOut)
def save_progress(course_id: str, body: ProgressIn) -> ProgressOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    try:
        result = sections_service.save_progress(course_id, body.section_id, body.scroll_pos)
    except sections_service.InvalidSectionForCourseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ProgressOut.model_validate(result)


@router.get("/{course_id}/progress", operation_id="get_progress", response_model=ProgressOut)
def get_progress(course_id: str) -> ProgressOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return ProgressOut.model_validate(sections_service.get_progress(course_id))
