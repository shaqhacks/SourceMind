from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from app.schemas import (
    GenerateTestIn,
    GenerateTestOut,
    RetakeTestOut,
    SubmitTestIn,
    SubmitTestOut,
    TestAttemptOut,
    TestSummaryOut,
)
from app.services import courses_service, learner_context, tests_service

router = APIRouter(tags=["tests"])


@router.post(
    "/api/courses/{course_id}/tests",
    operation_id="generate_test",
    status_code=202,
    response_model=GenerateTestOut,
)
def generate_test(
    course_id: str,
    request: Request,
    response: Response,
    body: GenerateTestIn = GenerateTestIn(),
) -> GenerateTestOut:
    learner_id = learner_context.ensure_learner_key(request, response)
    try:
        job_id = tests_service.start_test_generation(
            course_id,
            body.section_ids,
            body.chapter_label,
            learner_id=learner_id,
        )
    except tests_service.CourseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except tests_service.ChapterNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return GenerateTestOut(job_id=job_id)


@router.get("/api/tests/{attempt_id}", operation_id="get_test", response_model=TestAttemptOut)
def get_test(attempt_id: str, request: Request, response: Response) -> TestAttemptOut:
    learner_id = learner_context.ensure_learner_key(request, response)
    result = tests_service.get_test(attempt_id, learner_id=learner_id)
    if result is None:
        raise HTTPException(status_code=404, detail="test attempt not found")
    return TestAttemptOut.model_validate(result)


@router.post("/api/tests/{attempt_id}/submit", operation_id="submit_test", response_model=SubmitTestOut)
def submit_test(
    attempt_id: str, body: SubmitTestIn, request: Request, response: Response
) -> SubmitTestOut:
    learner_id = learner_context.ensure_learner_key(request, response)
    try:
        result = tests_service.submit_test(attempt_id, body.answers, learner_id=learner_id)
    except tests_service.TestAlreadySubmittedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="test attempt not found")
    return SubmitTestOut.model_validate(result)


@router.get(
    "/api/courses/{course_id}/tests",
    operation_id="list_tests",
    response_model=list[TestSummaryOut],
)
def list_tests(course_id: str, request: Request, response: Response) -> list[TestSummaryOut]:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    learner_id = learner_context.ensure_learner_key(request, response)
    return [
        TestSummaryOut.model_validate(t)
        for t in tests_service.list_tests(course_id, learner_id=learner_id)
    ]


@router.post(
    "/api/tests/{test_id}/attempts",
    operation_id="retake_test",
    status_code=201,
    response_model=RetakeTestOut,
)
def retake_test(test_id: str, request: Request, response: Response) -> RetakeTestOut:
    learner_id = learner_context.ensure_learner_key(request, response)
    attempt_id = tests_service.retake_test(test_id, learner_id=learner_id)
    if attempt_id is None:
        raise HTTPException(status_code=404, detail="test not found")
    return RetakeTestOut(attempt_id=attempt_id)
