from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, Response

from app.schemas import PracticeAssessmentOut, SubmitPracticeAnswerIn, SubmitPracticeAnswerOut
from app.services import practice_service

router = APIRouter(tags=["practice"])


def _learner_key(request: Request, response: Response) -> str:
    learner_key = request.cookies.get(practice_service.LEARNER_COOKIE)
    if learner_key is not None:
        return learner_key

    learner_key = str(uuid.uuid4())
    response.set_cookie(
        practice_service.LEARNER_COOKIE,
        learner_key,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return learner_key


@router.get(
    "/api/courses/{course_id}/sections/{section_id}/practice-assessment",
    operation_id="get_practice_assessment",
    response_model=PracticeAssessmentOut,
)
def get_practice_assessment(
    course_id: str, section_id: str, request: Request, response: Response
) -> PracticeAssessmentOut:
    learner_key = _learner_key(request, response)
    try:
        status_code, result = practice_service.get_assessment(course_id, section_id, learner_key)
    except practice_service.SectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except practice_service.NotPracticeSectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response.status_code = status_code
    return PracticeAssessmentOut.model_validate(result)


@router.post(
    "/api/courses/{course_id}/sections/{section_id}/practice-assessment",
    operation_id="start_practice_assessment",
    status_code=202,
    response_model=PracticeAssessmentOut,
)
def start_practice_assessment(
    course_id: str, section_id: str, request: Request, response: Response
) -> PracticeAssessmentOut:
    _learner_key(request, response)
    try:
        status_code, result = practice_service.start_assessment(course_id, section_id)
    except practice_service.SectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except practice_service.NotPracticeSectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response.status_code = status_code
    return PracticeAssessmentOut.model_validate(result)


@router.post(
    "/api/courses/{course_id}/practice-questions/{question_id}/answer",
    operation_id="submit_practice_answer",
    response_model=SubmitPracticeAnswerOut,
)
def submit_practice_answer(
    course_id: str,
    question_id: str,
    body: SubmitPracticeAnswerIn,
    request: Request,
    response: Response,
) -> SubmitPracticeAnswerOut:
    learner_key = _learner_key(request, response)
    try:
        result = practice_service.submit_answer(
            course_id, question_id, learner_key, body.selected_index
        )
    except practice_service.PracticeQuestionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except practice_service.InvalidChoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return SubmitPracticeAnswerOut.model_validate(result)
