from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import SkillGraphImportOut, SkillGraphIn
from app.services import courses_service, skills_service

router = APIRouter(prefix="/api/courses/{course_id}/skills", tags=["skills"])


@router.put(
    "/graph", operation_id="import_skill_graph", response_model=SkillGraphImportOut
)
def import_skill_graph(course_id: str, body: SkillGraphIn) -> SkillGraphImportOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    try:
        result = skills_service.import_graph(course_id, body.model_dump())
    except skills_service.GraphValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SkillGraphImportOut.model_validate(result)
