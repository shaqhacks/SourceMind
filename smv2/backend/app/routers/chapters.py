from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import ChapterOut, StudyNextItemOut
from app.services import chapters_service, courses_service, study_service

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


@router.get(
    "/api/courses/{course_id}/study-next",
    operation_id="study_next",
    response_model=list[StudyNextItemOut],
)
def study_next(course_id: str) -> list[StudyNextItemOut]:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return [StudyNextItemOut.model_validate(s) for s in study_service.study_next(course_id)]
