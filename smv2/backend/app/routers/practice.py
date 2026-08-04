from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from app.schemas import PracticeAssessmentOut, SubmitPracticeAnswerIn, SubmitPracticeAnswerOut
from app.services import learner_context, practice_service

router = APIRouter(tags=["practice"])


def _existing_learner_key(request: Request) -> str | None:
    return learner_context.existing_learner_key(request)


def _ensure_learner_key(request: Request, response: Response) -> str:
    return learner_context.ensure_learner_key(request, response)


@router.get(
    "/api/courses/{course_id}/sections/{section_id}/practice-assessment",
    operation_id="get_practice_assessment",
    response_model=PracticeAssessmentOut,
)
def get_practice_assessment(
    course_id: str, section_id: str, request: Request, response: Response
) -> PracticeAssessmentOut:
    try:
        status_code, result = practice_service.get_assessment(
            course_id, section_id, _existing_learner_key(request)
        )
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
    _ensure_learner_key(request, response)
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
    learner_key = _ensure_learner_key(request, response)
    try:
        result = practice_service.submit_answer(
            course_id, question_id, learner_key, body.selected_index
        )
    except practice_service.PracticeQuestionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except practice_service.InvalidChoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return SubmitPracticeAnswerOut.model_validate(result)
