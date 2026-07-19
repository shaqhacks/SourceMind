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

from pydantic import BaseModel, Field, StrictInt


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
    html_status: Literal["none", "converting", "ready", "failed"]
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
    origin: Literal["generated", "user"]
    created_at: datetime

    model_config = {"from_attributes": True}


class UpdateCardIn(BaseModel):
    front_md: str
    back_md: str


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


class SubmitTestQuestionResultOut(BaseModel):
    correct: bool
    correct_index: int
    explanation: str
    your_answer: int | None


class TestAttemptOut(BaseModel):
    """One attempt at a Test deck's persisted questions (ADR-022) —
    questions are redacted to {question, choices} until this attempt is
    submitted (score is None); answers/results are None until then too.
    """

    id: str
    test_id: str
    course_id: str
    chapter_label: str | None
    score: float | None
    questions: list[TestQuestionOut]
    answers: list[int] | None
    results: list[SubmitTestQuestionResultOut] | None
    created_at: datetime


class TestAttemptSummaryOut(BaseModel):
    id: str
    score: float | None
    created_at: datetime


class TestSummaryOut(BaseModel):
    """One generated deck plus its full attempt history, newest first —
    retaking a test (ADR-022) adds another entry to `attempts` rather than
    a whole new top-level row.
    """

    id: str
    course_id: str
    chapter_label: str | None
    question_count: int
    created_at: datetime
    attempts: list[TestAttemptSummaryOut]


class RetakeTestOut(BaseModel):
    attempt_id: str


class SubmitTestIn(BaseModel):
    answers: list[int]


class SubmitTestOut(BaseModel):
    score: float
    results: list[SubmitTestQuestionResultOut]
    added_card_ids: list[str]
    due_now_count: int


# --- Practice assessments -------------------------------------------------


class PracticeConceptOut(BaseModel):
    id: str
    slug: str
    label: str


class PracticeAnsweredOut(BaseModel):
    selected_index: int
    correct: bool
    correct_index: int
    explanation_md: str
    points_delta: int
    mastery_points: int
    answered_at: datetime


class PracticeQuestionOut(BaseModel):
    id: str
    problem_number: str
    source_ref: str
    stem_md: str
    choices: list[str]
    concept: PracticeConceptOut
    answered: PracticeAnsweredOut | None


class PracticeAssessmentOut(BaseModel):
    status: Literal["ready", "generating", "failed", "not_started"]
    section_id: str
    questions: list[PracticeQuestionOut] = Field(default_factory=list)
    run_id: str | None = None
    job_id: str | None = None
    message: str | None = None


class SubmitPracticeAnswerIn(BaseModel):
    selected_index: StrictInt


class SubmitPracticeAnswerOut(BaseModel):
    question_id: str
    selected_index: int
    correct: bool
    correct_index: int
    explanation_md: str
    concept: PracticeConceptOut
    points_delta: int
    mastery_points: int
    already_answered: bool


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


class StudyNextItemOut(BaseModel):
    """One deterministic study suggestion (ADR-022, app.services.study_service).
    `detail` holds whatever raw numbers back `reason` — {"best_score":
    ...} for low_test_score, {"due_count": ...} for due_cards, {} for
    unread, {"days_since": ...} for stale.
    """

    chapter_label: str | None
    reason: Literal["low_test_score", "due_cards", "unread", "stale"]
    detail: dict[str, Any]


# --- Highlights ------------------------------------------------------------


HighlightColor = Literal["yellow", "green", "blue", "pink"]


class HighlightIn(BaseModel):
    """Anchor fields are opaque to the backend — the frontend's quote
    matcher owns their semantics. page is 1-based here like every page in
    this API surface (see module docstring)."""

    section_id: str
    exact: str = Field(min_length=1, max_length=2000)
    prefix: str = Field(default="", max_length=64)
    suffix: str = Field(default="", max_length=64)
    occurrence: int = Field(default=0, ge=0)
    page: int | None = Field(default=None, ge=1)
    color: HighlightColor = "yellow"
    surface: Literal["source", "pdf"] = "source"


class HighlightUpdateIn(BaseModel):
    """PATCH semantics via model_dump(exclude_unset=True): an omitted field
    is left alone; an explicit null note_md clears the note."""

    note_md: str | None = Field(default=None, max_length=20000)
    color: HighlightColor | None = None


class HighlightOut(BaseModel):
    id: str
    course_id: str
    section_id: str
    exact: str
    prefix: str
    suffix: str
    occurrence: int
    page: int | None
    color: HighlightColor
    surface: Literal["source", "pdf"]
    note_md: str | None
    created_at: datetime
    updated_at: datetime


# --- Chat ------------------------------------------------------------


class ChatSelectionIn(BaseModel):
    """A passage the student selected in the reader — same 2000-char cap as
    HighlightIn.exact. Grounds this turn in that passage (ADR-024 feature)."""

    section_id: str
    exact: str = Field(min_length=1, max_length=2000)


class ChatIn(BaseModel):
    message: str
    selection: ChatSelectionIn | None = None


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
