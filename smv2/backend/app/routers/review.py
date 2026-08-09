from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.schemas import GradeCardIn, GradeCardOut, ReviewQueueOut, ReviewSummaryOut
from app.services import courses_service, learner_context, srs_service

router = APIRouter(tags=["review"])


@router.get(
    "/api/courses/{course_id}/review/queue", operation_id="review_queue", response_model=ReviewQueueOut
)
def review_queue(
    course_id: str,
    request: Request,
    response: Response,
    limit: int = Query(default=20, ge=1, le=200),
    scope: Literal["available", "all", "needs_attention"] = "available",
    chapter_label: str | None = None,
) -> ReviewQueueOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    learner_id = learner_context.ensure_learner_key(request, response)
    return ReviewQueueOut.model_validate(
        srs_service.get_review_queue(
            course_id,
            limit,
            learner_id=learner_id,
            scope=scope,
            chapter_label=chapter_label,
        )
    )


@router.post("/api/cards/{card_id}/grade", operation_id="grade_card", response_model=GradeCardOut)
def grade_card(card_id: str, body: GradeCardIn, request: Request, response: Response) -> GradeCardOut:
    if not (1 <= body.grade <= 4):
        raise HTTPException(status_code=422, detail="grade must be between 1 and 4")

    learner_id = learner_context.ensure_learner_key(request, response)
    result = srs_service.grade_card(card_id, body.grade, body.elapsed_ms, learner_id=learner_id)
    if result is None:
        raise HTTPException(status_code=404, detail="card not found")
    return GradeCardOut.model_validate(result)


@router.get("/api/review/summary", operation_id="review_summary", response_model=ReviewSummaryOut)
def review_summary(request: Request, response: Response) -> ReviewSummaryOut:
    learner_id = learner_context.ensure_learner_key(request, response)
    return ReviewSummaryOut.model_validate(srs_service.get_review_summary(learner_id=learner_id))
