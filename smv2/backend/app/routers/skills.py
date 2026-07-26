from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import SkillDetailOut, SkillGraphImportOut, SkillGraphIn, SkillMapOut
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


@router.get("", operation_id="get_skill_map", response_model=SkillMapOut)
def get_skill_map(course_id: str) -> SkillMapOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    data = skills_service.get_skill_map(course_id)
    return SkillMapOut.model_validate(data)


@router.get("/{concept_id}", operation_id="get_skill_detail", response_model=SkillDetailOut)
def get_skill_detail(course_id: str, concept_id: str) -> SkillDetailOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    detail = skills_service.get_skill_detail(course_id, concept_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="concept not found")
    return SkillDetailOut.model_validate(detail)
