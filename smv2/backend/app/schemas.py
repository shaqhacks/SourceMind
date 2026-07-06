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
    failed_asset_count: int = 0
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
    """Reader list view — no body_md (can be large); use get_section for that.

    page_start/page_end here are already 1-based, inclusive page numbers
    into asset_id's own PDF (not course-wide) — app.services.sections_service
    converts from the DB's 0-based storage (app.pipeline.outline_detect's
    SectionBounds convention) via to_display_page() before this schema is
    ever built. That means a caller driving pdf.js (which numbers pages
    1-based) can pass this value straight through — do NOT add another +1
    "to be safe," that would double-offset it.
    """

    id: str
    title: str
    order_index: int
    asset_id: str | None
    page_start: int | None
    page_end: int | None
    lesson_status: str
    has_content: bool
    word_count: int
    kind: Literal["content", "practice", "answers"]
    chapter_label: str | None


class SectionDetailOut(BaseModel):
    """page_start/page_end convention: see SectionOut's docstring above —
    already 1-based page numbers, ready to hand to a PDF viewer as-is."""

    id: str
    course_id: str
    title: str
    order_index: int
    asset_id: str | None
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
    kind: Literal["content", "practice", "answers"]
    chapter_label: str | None
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


# --- Cards -------------------------------------------------------------


class GenerateCardsOut(BaseModel):
    job_id: str


class CardOut(BaseModel):
    id: str
    section_id: str
    front_md: str
    back_md: str
    position: int
    created_at: datetime

    model_config = {"from_attributes": True}


# --- Spaced repetition ---------------------------------------------------


class ReviewQueueCardOut(BaseModel):
    id: str
    section_id: str
    front_md: str
    back_md: str
    due_at: datetime | None
    is_new: bool


class ReviewQueueOut(BaseModel):
    cards: list[ReviewQueueCardOut]
    due: int
    new: int
    total: int


class GradeCardIn(BaseModel):
    grade: int
    elapsed_ms: int | None = None


class GradeCardOut(BaseModel):
    next_due_at: datetime
    remaining_due: int


class CourseReviewSummaryOut(BaseModel):
    course_id: str
    title: str
    due_count: int
    new_count: int


class ReviewSummaryOut(BaseModel):
    courses: list[CourseReviewSummaryOut]
    due_total: int
    daily_throughput: float
    backlog_warning: bool


# --- Quizzes -------------------------------------------------------------


class GenerateTestIn(BaseModel):
    section_ids: list[str] | None = None
    chapter_label: str | None = None


class GenerateTestOut(BaseModel):
    job_id: str


class TestQuestionOut(BaseModel):
    question: str
    choices: list[str]
    correct_index: int | None = None
    explanation: str | None = None


class TestAttemptOut(BaseModel):
    id: str
    course_id: str
    score: float | None
    chapter_label: str | None
    questions: list[TestQuestionOut]
    created_at: datetime


class TestAttemptSummaryOut(BaseModel):
    id: str
    course_id: str
    score: float | None
    chapter_label: str | None
    question_count: int
    created_at: datetime


class SubmitTestIn(BaseModel):
    answers: list[int]


class SubmitTestQuestionResultOut(BaseModel):
    correct: bool
    correct_index: int
    explanation: str
    your_answer: int | None


class SubmitTestOut(BaseModel):
    score: float
    results: list[SubmitTestQuestionResultOut]
    added_card_ids: list[str]


# --- Chapters --------------------------------------------------------------


class ChapterTestStatsOut(BaseModel):
    attempts: int
    best_score: float | None
    latest_score: float | None


class ChapterOut(BaseModel):
    chapter_label: str | None
    section_ids: list[str]
    practice_section_ids: list[str]
    answers_section_ids: list[str]
    test_stats: ChapterTestStatsOut | None


# --- Chat ------------------------------------------------------------


class ChatIn(BaseModel):
    message: str


class ChatCitationOut(BaseModel):
    n: int
    section_id: str
    page: int | None
    source_ref: str


class ChatOut(BaseModel):
    reply_md: str
    citations: list[ChatCitationOut]


class ChatTurnOut(BaseModel):
    id: str
    role: str
    content: str
    citations: list[dict[str, Any]] | None
    created_at: datetime

    model_config = {"from_attributes": True}
