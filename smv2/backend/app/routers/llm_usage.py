from __future__ import annotations

from fastapi import APIRouter

from app.schemas import LlmStatusOut, LlmUsageOut
from app.services import llm_readiness_service, llm_usage_service

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get("/usage", operation_id="llm_usage", response_model=LlmUsageOut)
def llm_usage(course_id: str | None = None) -> LlmUsageOut:
    return LlmUsageOut.model_validate(llm_usage_service.get_usage(course_id))


@router.get("/status", operation_id="llm_status", response_model=LlmStatusOut)
def llm_status() -> LlmStatusOut:
    return LlmStatusOut.model_validate(llm_readiness_service.status_payload())


@router.post("/status/check", operation_id="llm_status_check", response_model=LlmStatusOut)
def llm_status_check() -> LlmStatusOut:
    return LlmStatusOut.model_validate(llm_readiness_service.check_payload())
