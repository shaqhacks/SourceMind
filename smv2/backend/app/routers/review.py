from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import GradeCardIn, GradeCardOut, ReviewQueueOut, ReviewSummaryOut
from app.services import courses_service, srs_service

router = APIRouter(tags=["review"])


@router.get(
    "/api/courses/{course_id}/review/queue", operation_id="review_queue", response_model=ReviewQueueOut
)
def review_queue(course_id: str, limit: int = Query(default=20, ge=1, le=200)) -> ReviewQueueOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return ReviewQueueOut.model_validate(srs_service.get_review_queue(course_id, limit))


@router.post("/api/cards/{card_id}/grade", operation_id="grade_card", response_model=GradeCardOut)
def grade_card(card_id: str, body: GradeCardIn) -> GradeCardOut:
    if not (1 <= body.grade <= 4):
        raise HTTPException(status_code=422, detail="grade must be between 1 and 4")

    result = srs_service.grade_card(card_id, body.grade, body.elapsed_ms)
    if result is None:
        raise HTTPException(status_code=404, detail="card not found")
    return GradeCardOut.model_validate(result)


@router.get("/api/review/summary", operation_id="review_summary", response_model=ReviewSummaryOut)
def review_summary() -> ReviewSummaryOut:
    return ReviewSummaryOut.model_validate(srs_service.get_review_summary())
