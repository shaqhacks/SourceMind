from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from app.schemas import (
    DiagnosticBlindCaseOut,
    DiagnosticDisagreementReasonIn,
    DiagnosticJudgmentIn,
    DiagnosticJudgmentOut,
    DiagnosticValidationSummaryOut,
)
from app.services import courses_service, diagnostic_validation_service, learner_context

router = APIRouter(
    prefix="/api/courses/{course_id}/diagnostics/validation",
    tags=["diagnostic-validation"],
)


@router.get("/next", operation_id="next_diagnostic_validation", response_model=DiagnosticBlindCaseOut | None)
def next_diagnostic_validation(
    course_id: str, request: Request, response: Response
) -> DiagnosticBlindCaseOut | None:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    learner_id = learner_context.ensure_learner_key(request, response)
    try:
        case = diagnostic_validation_service.next_blind_case(course_id, learner_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DiagnosticBlindCaseOut(**case) if case is not None else None


@router.post(
    "/judgments",
    operation_id="submit_diagnostic_judgment",
    status_code=201,
    response_model=DiagnosticJudgmentOut,
)
def submit_diagnostic_judgment(
    course_id: str,
    payload: DiagnosticJudgmentIn,
    request: Request,
    response: Response,
) -> DiagnosticJudgmentOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    learner_id = learner_context.ensure_learner_key(request, response)
    try:
        record = diagnostic_validation_service.submit_judgment(
            course_id,
            learner_id,
            concept_id=payload.concept_id,
            judgment=payload.judgment,
            disagreement_reason=payload.disagreement_reason,
            notes_md=payload.notes_md,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return DiagnosticJudgmentOut.model_validate(record)


@router.patch(
    "/judgments/{judgment_id}/reason",
    operation_id="record_diagnostic_disagreement_reason",
    response_model=DiagnosticJudgmentOut,
)
def record_diagnostic_disagreement_reason(
    course_id: str,
    judgment_id: str,
    payload: DiagnosticDisagreementReasonIn,
) -> DiagnosticJudgmentOut:
    try:
        record = diagnostic_validation_service.record_disagreement_reason(
            course_id,
            judgment_id,
            payload.disagreement_reason,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return DiagnosticJudgmentOut.model_validate(record)


@router.get("/summary", operation_id="diagnostic_validation_summary", response_model=DiagnosticValidationSummaryOut)
def diagnostic_validation_summary(course_id: str) -> DiagnosticValidationSummaryOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return DiagnosticValidationSummaryOut(**diagnostic_validation_service.course_summary(course_id))
