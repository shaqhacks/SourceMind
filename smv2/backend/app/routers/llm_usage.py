from __future__ import annotations

from fastapi import APIRouter

from app.schemas import LlmUsageOut
from app.services import llm_usage_service

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get("/usage", operation_id="llm_usage", response_model=LlmUsageOut)
def llm_usage(course_id: str | None = None) -> LlmUsageOut:
    return LlmUsageOut.model_validate(llm_usage_service.get_usage(course_id))
