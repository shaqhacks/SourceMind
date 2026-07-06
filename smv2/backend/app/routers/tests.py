from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import (
    GenerateTestIn,
    GenerateTestOut,
    SubmitTestIn,
    SubmitTestOut,
    TestAttemptOut,
    TestAttemptSummaryOut,
)
from app.services import courses_service, tests_service

router = APIRouter(tags=["tests"])


@router.post(
    "/api/courses/{course_id}/tests",
    operation_id="generate_test",
    status_code=202,
    response_model=GenerateTestOut,
)
def generate_test(course_id: str, body: GenerateTestIn = GenerateTestIn()) -> GenerateTestOut:
    try:
        job_id = tests_service.start_test_generation(course_id, body.section_ids, body.chapter_label)
    except tests_service.CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except tests_service.ChapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return GenerateTestOut(job_id=job_id)


@router.get("/api/tests/{attempt_id}", operation_id="get_test", response_model=TestAttemptOut)
def get_test(attempt_id: str) -> TestAttemptOut:
    result = tests_service.get_test(attempt_id)
    if result is None:
        raise HTTPException(status_code=404, detail="test attempt not found")
    return TestAttemptOut.model_validate(result)


@router.post("/api/tests/{attempt_id}/submit", operation_id="submit_test", response_model=SubmitTestOut)
def submit_test(attempt_id: str, body: SubmitTestIn) -> SubmitTestOut:
    try:
        result = tests_service.submit_test(attempt_id, body.answers)
    except tests_service.TestAlreadySubmittedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="test attempt not found")
    return SubmitTestOut.model_validate(result)


@router.get(
    "/api/courses/{course_id}/tests",
    operation_id="list_tests",
    response_model=list[TestAttemptSummaryOut],
)
def list_tests(course_id: str) -> list[TestAttemptSummaryOut]:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return [TestAttemptSummaryOut.model_validate(a) for a in tests_service.list_tests(course_id)]
