from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.schemas import GenerateAllLessonsOut, GenerateLessonOut, LessonEstimateOut
from app.services import courses_service, lessons_service, llm_readiness_service

router = APIRouter(tags=["lessons"])


@router.post(
    "/api/sections/{section_id}/lesson",
    operation_id="generate_lesson",
    status_code=202,
    response_model=GenerateLessonOut,
)
def generate_lesson(section_id: str, force: bool = Query(default=False)) -> GenerateLessonOut:
    try:
        job_id = lessons_service.start_lesson_generation(section_id, force=force)
    except llm_readiness_service.LlmReadinessUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc
    except lessons_service.SectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except lessons_service.LessonAlreadyInProgressError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return GenerateLessonOut(job_id=job_id)


@router.post(
    "/api/courses/{course_id}/lessons",
    operation_id="generate_all_lessons",
    status_code=202,
    response_model=GenerateAllLessonsOut,
)
def generate_all_lessons(course_id: str) -> GenerateAllLessonsOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")

    try:
        job_ids, skipped = lessons_service.start_all_lesson_generations(course_id)
    except llm_readiness_service.LlmReadinessUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc
    return GenerateAllLessonsOut(job_ids=job_ids, skipped=skipped)


@router.get(
    "/api/sections/{section_id}/lesson/estimate",
    operation_id="lesson_estimate",
    response_model=LessonEstimateOut,
)
def lesson_estimate(section_id: str) -> LessonEstimateOut:
    estimate = lessons_service.estimate_lesson(section_id)
    if estimate is None:
        raise HTTPException(status_code=404, detail="section not found")
    return LessonEstimateOut.model_validate(estimate)
