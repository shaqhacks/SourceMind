from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from app.schemas import (
    RetentionAssignmentIn,
    RetentionAssignmentOut,
    RetentionProbeIn,
    RetentionProbeOut,
    RetentionStudyIn,
    RetentionStudyOut,
)
from app.services import courses_service, learner_context, retention_study_service

router = APIRouter(prefix="/api/courses/{course_id}/retention-studies", tags=["retention-studies"])


@router.post("", operation_id="create_retention_study", status_code=201, response_model=RetentionStudyOut)
def create_retention_study(course_id: str, payload: RetentionStudyIn) -> RetentionStudyOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    try:
        study = retention_study_service.create_study(course_id, **payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RetentionStudyOut.model_validate(study)


@router.post("/{study_id}/assignments", operation_id="create_retention_assignment", status_code=201, response_model=RetentionAssignmentOut)
def create_retention_assignment(
    course_id: str,
    study_id: str,
    payload: RetentionAssignmentIn,
    request: Request,
    response: Response,
) -> RetentionAssignmentOut:
    learner_id = learner_context.ensure_learner_key(request, response)
    try:
        row = retention_study_service.assign_learner(
            study_id,
            course_id,
            learner_id,
            payload.concept_id,
            workload_target=payload.workload_target,
        )
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RetentionAssignmentOut.model_validate(row)


@router.post("/{study_id}/assignments/{assignment_id}/probes", operation_id="schedule_retention_probe", status_code=201, response_model=RetentionProbeOut)
def schedule_retention_probe(
    course_id: str,
    study_id: str,
    assignment_id: str,
    payload: RetentionProbeIn,
) -> RetentionProbeOut:
    try:
        probe = retention_study_service.schedule_probe(assignment_id, payload.learning_claim_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RetentionProbeOut.model_validate(probe)
