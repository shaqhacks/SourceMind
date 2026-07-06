from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import ChapterOut
from app.services import chapters_service, courses_service

router = APIRouter(tags=["chapters"])


@router.get(
    "/api/courses/{course_id}/chapters",
    operation_id="list_chapters",
    response_model=list[ChapterOut],
)
def list_chapters(course_id: str) -> list[ChapterOut]:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return [ChapterOut.model_validate(c) for c in chapters_service.get_chapters(course_id)]
