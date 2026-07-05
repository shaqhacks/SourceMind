"""Pydantic request/response schemas, kept separate from routers so router
imports stay limited to fastapi/pydantic/app.services/app.schemas/app.config.

Page numbers are 1-based everywhere in this API surface (page_start,
page_end, at_page) for end-user readability; the DB/pipeline layers store
0-based page indices internally (matching PyMuPDF's own convention) and the
service layer is responsible for the +1/-1 conversion at this boundary.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    type: str
    payload: dict[str, Any] | None = None


class JobOut(BaseModel):
    id: str
    type: str
    status: str
    payload: dict[str, Any] | None
    result: dict[str, Any] | None
    progress: dict[str, Any] | None
    error: str | None
    attempts: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CourseCreate(BaseModel):
    title: str


class ProgressSummary(BaseModel):
    section_id: str | None
    scroll_pos: float
    updated_at: datetime | None


class CourseOut(BaseModel):
    id: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime
    section_count: int = 0
    progress: ProgressSummary | None = None

    model_config = {"from_attributes": True}


class AssetOut(BaseModel):
    id: str
    course_id: str
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    page_count: int | None
    status: str
    error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IngestStartOut(BaseModel):
    job_id: str


class SectionOut(BaseModel):
    """Reader list view — no body_md (can be large); use get_section for that."""

    id: str
    title: str
    order_index: int
    page_start: int | None
    page_end: int | None
    lesson_status: str
    has_content: bool
    word_count: int


class SectionDetailOut(BaseModel):
    id: str
    course_id: str
    title: str
    order_index: int
    page_start: int | None
    page_end: int | None
    body_md: str
    content_hash: str
    lesson_md: str | None
    lesson_status: str
    lesson_stale: bool
    lesson_model: str | None
    lesson_prompt_version: str | None
    extractor_version: str | None
    created_at: datetime
    updated_at: datetime


class ProgressIn(BaseModel):
    section_id: str | None = None
    scroll_pos: float = 0.0


class ProgressOut(BaseModel):
    course_id: str
    section_id: str | None
    scroll_pos: float
    updated_at: datetime | None


class RenameOp(BaseModel):
    type: Literal["rename"]
    section_id: str
    title: str


class ReorderOp(BaseModel):
    type: Literal["reorder"]
    order: list[str]


class DeleteOp(BaseModel):
    type: Literal["delete"]
    section_id: str


class MergeOp(BaseModel):
    type: Literal["merge"]
    section_ids: list[str]


class SplitOp(BaseModel):
    type: Literal["split"]
    section_id: str
    at_page: int  # 1-based; converted to 0-based before reaching the pipeline


OutlineOp = Annotated[
    Union[RenameOp, ReorderOp, DeleteOp, MergeOp, SplitOp],
    Field(discriminator="type"),
]


class OutlineEditRequest(BaseModel):
    operations: list[OutlineOp]


class GenerateLessonOut(BaseModel):
    job_id: str


class GenerateAllLessonsOut(BaseModel):
    job_ids: list[str]
    skipped: int


class LessonEstimateOut(BaseModel):
    est_seconds: float
    est_cost_usd: float | None
    based_on_calls: int


class LlmUsageOut(BaseModel):
    calls: int
    input_tokens: int
    output_tokens: int
    est_cost_usd: float
