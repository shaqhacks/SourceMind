from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from app.schemas import (
    SkillDetailOut,
    SkillGraphImportOut,
    SkillGraphIn,
    SkillMapOut,
    SkillStatusOut,
)
from app.services import courses_service, learner_context, skills_service

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


@router.get("/status", operation_id="get_skill_status", response_model=SkillStatusOut)
def get_skill_status(course_id: str) -> SkillStatusOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return SkillStatusOut.model_validate(skills_service.get_skill_status(course_id))


@router.get("", operation_id="get_skill_map", response_model=SkillMapOut)
def get_skill_map(course_id: str, request: Request, response: Response) -> SkillMapOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    learner_id = learner_context.ensure_learner_key(request, response)
    data = skills_service.get_skill_map(course_id, learner_id=learner_id)
    return SkillMapOut.model_validate(data)


@router.get("/{concept_id}", operation_id="get_skill_detail", response_model=SkillDetailOut)
def get_skill_detail(
    course_id: str, concept_id: str, request: Request, response: Response
) -> SkillDetailOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    learner_id = learner_context.ensure_learner_key(request, response)
    detail = skills_service.get_skill_detail(course_id, concept_id, learner_id=learner_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="concept not found")
    return SkillDetailOut.model_validate(detail)
