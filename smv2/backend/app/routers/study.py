from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.schemas import AdaptiveStudyQueueOut, JobOut
from app.services import (
    adaptive_study_service,
    courses_service,
    learner_context,
    llm_readiness_service,
)

router = APIRouter(prefix="/api/courses/{course_id}/study", tags=["study"])


@router.get("/queue", operation_id="adaptive_study_queue", response_model=AdaptiveStudyQueueOut)
def adaptive_study_queue(
    course_id: str,
    request: Request,
    response: Response,
    limit: int = Query(default=20, ge=1, le=100),
) -> AdaptiveStudyQueueOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    learner_id = learner_context.ensure_learner_key(request, response)
    return AdaptiveStudyQueueOut(
        activities=adaptive_study_service.get_queue(
            course_id,
            learner_id,
            limit=limit,
        )
    )


@router.post(
    "/concepts/{concept_id}/replenish",
    operation_id="replenish_concept_practice",
    status_code=202,
    response_model=JobOut,
)
def replenish_concept_practice(course_id: str, concept_id: str) -> JobOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    try:
        job = adaptive_study_service.start_replenishment(course_id, concept_id)
    except llm_readiness_service.LlmReadinessUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JobOut.model_validate(job)
