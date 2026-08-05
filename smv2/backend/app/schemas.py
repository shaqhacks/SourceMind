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

from pydantic import BaseModel, computed_field, Field, StrictInt


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

    @computed_field
    @property
    def retryable(self) -> bool:
        from app.jobs.registry import RETRYABLE_JOB_TYPES

        return self.type in RETRYABLE_JOB_TYPES


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


# --- Versioned curriculum -------------------------------------------------


class CurriculumExtractionOut(BaseModel):
    job_id: str
    curriculum_version_id: str


class CurriculumDraftIn(BaseModel):
    label: str | None = None


class CurriculumDraftOut(BaseModel):
    curriculum_version_id: str


class CurriculumConceptOut(BaseModel):
    id: str
    stable_key: str
    label: str
    description_md: str
    aliases: list[str]
    chapter_label: str | None
    review_state: str
    is_active: bool


class CurriculumClaimOut(BaseModel):
    id: str
    stable_key: str
    concept_id: str
    statement: str
    success_criteria_md: str
    aliases: list[str]
    cognitive_demand: str | None
    review_state: str
    is_active: bool


class CurriculumRelationOut(BaseModel):
    id: str
    from_concept_id: str
    to_concept_id: str | None
    kind: str
    external_ref: str | None
    confidence: float | None
    rationale_md: str | None
    review_state: str


class CurriculumSourceOut(BaseModel):
    id: str
    concept_id: str
    learning_claim_id: str | None
    section_id: str | None
    source_ref: str
    excerpt_md: str | None
    source_content_hash: str | None
    confidence: float | None
    rationale_md: str | None
    review_state: str
    stale: bool


class CurriculumVersionOut(BaseModel):
    id: str
    course_id: str
    parent_version_id: str | None
    status: str
    is_current: bool
    label: str | None
    created_at: datetime
    published_at: datetime | None
    concepts: list[CurriculumConceptOut]
    claims: list[CurriculumClaimOut]
    relations: list[CurriculumRelationOut]
    sources: list[CurriculumSourceOut]


class EvidenceMappingReviewOut(BaseModel):
    id: str
    evidence_item_id: str
    item_type: str
    item_preview: str
    concept_id: str
    concept_label: str
    learning_claim_id: str
    claim_statement: str
    role: str
    task_type: str
    cognitive_demand: str | None
    mapping_confidence: float | None
    review_state: str
    source_ref: str | None


class EvidenceMappingReviewIn(BaseModel):
    review_state: Literal["verified", "rejected"]


class CurriculumConceptEditIn(BaseModel):
    label: str = Field(min_length=1, max_length=500)
    description_md: str = Field(max_length=20000)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    chapter_label: str | None = Field(default=None, max_length=500)


class CurriculumClaimEditIn(BaseModel):
    concept_id: str | None = None
    statement: str | None = Field(default=None, min_length=1, max_length=5000)
    success_criteria_md: str | None = Field(default=None, max_length=10000)
    aliases: list[str] | None = Field(default=None, max_length=100)
    cognitive_demand: str | None = Field(default=None, max_length=100)
    review_state: Literal["unverified", "verified", "rejected"] | None = None
    is_active: bool | None = None


class CurriculumMergeIn(BaseModel):
    source_concept_ids: list[str] = Field(min_length=1, max_length=100)
    target_concept_id: str


class CurriculumSplitChildIn(BaseModel):
    stable_key: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=500)
    description_md: str = Field(default="", max_length=20000)


class CurriculumSplitIn(BaseModel):
    children: list[CurriculumSplitChildIn] = Field(min_length=2, max_length=20)


class StandardAlignmentIn(BaseModel):
    concept_id: str
    external_ref: str = Field(min_length=1, max_length=1000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    rationale_md: str | None = Field(default=None, max_length=5000)


class RelationReviewIn(BaseModel):
    review_state: Literal["unverified", "verified", "rejected"]


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


class LlmCapabilitiesOut(BaseModel):
    completion: bool
    embeddings: bool


class LlmStatusOut(BaseModel):
    provider: str
    model: str
    configured: bool
    available: bool
    capabilities: LlmCapabilitiesOut
    last_checked_at: str | None
    failure_category: str | None
    remediation: str | None


class LocalSettingsRolloutOut(BaseModel):
    local_settings_enabled: bool


class SettingsBootstrapOut(BaseModel):
    csrf_token: str
    rollout: LocalSettingsRolloutOut


class SettingsUpdateIn(BaseModel):
    provider: Literal["anthropic", "ollama"] | None = None
    model: str | None = Field(default=None, min_length=1, max_length=200)
    credentials: dict[str, str] = Field(default_factory=dict)


class SettingsClearIn(BaseModel):
    provider: Literal["anthropic", "ollama"]
    confirmation: str


class SettingsOut(BaseModel):
    provider: str
    model: str
    credentials_present: dict[str, bool]
    credentials: dict[str, str]
    rollout: LocalSettingsRolloutOut
    readiness: LlmStatusOut


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
    # Scheduler state going INTO the next grade (srs_service.schedule_next's
    # own convention) — a new card (is_new=True) gets the same bootstrap
    # values grade_card() uses when it has no ReviewState yet. Exposed so
    # the frontend can preview each grade's resulting interval without
    # guessing at state it doesn't have.
    interval_days: float
    ease: float
    reps: int


class ReviewQueueOut(BaseModel):
    cards: list[ReviewQueueCardOut]
    due: int
    new: int
    total: int


class AdaptiveStudyActivityOut(BaseModel):
    activity_type: Literal["flashcard", "question"]
    activity_id: str
    concept_id: str | None
    learning_claim_id: str | None
    reason: Literal[
        "targeted_remediation",
        "evidence_exploration",
        "due_review",
        "forgetting_risk",
        "retention_probe",
    ]
    readiness_state: str
    due_at: datetime | None
    payload: dict[str, Any]


class AdaptiveStudyQueueOut(BaseModel):
    activities: list[AdaptiveStudyActivityOut]


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
    readiness_estimate: float | None
    evidence_state: str
    evidence_count: int
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
    readiness_estimate: float | None
    evidence_state: str
    evidence_count: int
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


# --- Notes (positional margin notes, ADR margin-notes) ---------------


class NoteIn(BaseModel):
    """A margin note anchored to a page + a 0..1 vertical fraction. page is
    1-based here like every page in this API surface; anchor_y is top-origin."""

    section_id: str
    page: int = Field(ge=1)
    anchor_y: float = Field(ge=0.0, le=1.0)
    note_md: str = Field(min_length=1, max_length=20000)
    surface: Literal["pdf"] = "pdf"


class NoteUpdateIn(BaseModel):
    note_md: str | None = Field(default=None, min_length=1, max_length=20000)


class NoteOut(BaseModel):
    id: str
    course_id: str
    section_id: str
    surface: Literal["pdf"]
    page: int
    anchor_y: float
    note_md: str
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


# --- Skills / competency graph ----------------------------------------


class SkillGraphSectionRefIn(BaseModel):
    """Where a concept is taught within the course; rank orders multiple
    appearances, relevance_md is a short hand-written blurb (not a full
    note)."""

    section_id: str
    rank: int = Field(default=0, ge=0)
    relevance_md: str | None = Field(default=None, max_length=2000)


class SkillGraphConceptIn(BaseModel):
    slug: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=500)
    section_refs: list[SkillGraphSectionRefIn] = Field(default_factory=list, max_length=50)


class SkillGraphEdgeIn(BaseModel):
    """from_slug must be learned before to_slug — both must reference a
    slug present in this same payload's concepts list."""

    from_slug: str
    to_slug: str


class SkillGraphIn(BaseModel):
    concepts: list[SkillGraphConceptIn] = Field(max_length=500)
    edges: list[SkillGraphEdgeIn] = Field(default_factory=list, max_length=2000)


class SkillGraphImportOut(BaseModel):
    concept_count: int
    edge_count: int
    link_count: int


class SkillNodeOut(BaseModel):
    id: str
    slug: str
    label: str
    level: int
    status: str
    readiness_estimate: float | None = None
    evidence_state: str | None = None
    uncertainty: float | None = None
    posterior_lower: float | None = None
    posterior_upper: float | None = None
    quiz_estimate: float | None = None
    review_estimate: float | None = None
    effective_evidence_count: float | None = None
    distinct_item_count: int | None = None
    distinct_session_count: int | None = None
    trend: str | None = None
    forgetting_risk: float | None = None
    last_evidence_at: datetime | None = None


class SkillEdgeOut(BaseModel):
    from_id: str
    to_id: str
    kind: str  # "ready" | "review_suggested"


class SkillMapOut(BaseModel):
    nodes: list[SkillNodeOut]
    edges: list[SkillEdgeOut]


class SkillTaughtInOut(BaseModel):
    section_id: str
    chapter_label: str | None
    title: str
    rank: int
    relevance_md: str | None


class SkillMissedQuestionOut(BaseModel):
    question: str
    your_answer: str | None
    correct_answer: str
    source_test_id: str
    attempted_at: datetime


class SkillDetailOut(BaseModel):
    node: SkillNodeOut
    taught_in: list[SkillTaughtInOut]
    missed_questions: list[SkillMissedQuestionOut]
    cards_count: int
    quiz_correct: int
    quiz_wrong: int


class DiagnosticBlindCaseOut(BaseModel):
    concept_id: str
    concept_label: str
    concept_description_md: str
    evidence_available: bool


class DiagnosticJudgmentIn(BaseModel):
    concept_id: str
    judgment: Literal["insufficient", "not_struggling", "uncertain", "likely_struggling"]
    disagreement_reason: Literal[
        "model_estimate",
        "item_mapping",
        "concept_granularity",
        "insufficient_student_evidence",
        "instructor_disagreement",
    ] | None = None
    notes_md: str | None = None


class DiagnosticJudgmentOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    concept_id: str
    judgment: str
    disagreement_reason: str | None
    model_state: str
    readiness_estimate: float | None
    evidence_count: int
    model_version: str
    agreement: bool
    created_at: datetime

    @computed_field
    @property
    def requires_disagreement_reason(self) -> bool:
        return not self.agreement and self.disagreement_reason is None


class DiagnosticDisagreementReasonIn(BaseModel):
    disagreement_reason: Literal[
        "model_estimate",
        "item_mapping",
        "concept_granularity",
        "insufficient_student_evidence",
        "instructor_disagreement",
    ]


class DiagnosticValidationSummaryOut(BaseModel):
    sample_size: int
    agreement_count: int
    raw_agreement: float | None
    chance_adjusted_agreement: float | None
    sufficient_sample: bool
    pending_reason_count: int
    disagreement_reasons: dict[str, int]
    disagreements_by_concept: dict[str, int]


class RetentionStudyIn(BaseModel):
    name: str
    assignment_seed: str
    delay_start_days: int = Field(default=7, ge=1)
    delay_end_days: int = Field(default=14, ge=1)
    minimum_per_group: int = Field(default=20, ge=1)


class RetentionStudyOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    course_id: str
    name: str
    status: str
    assignment_seed: str
    protocol_version: str
    delay_start_days: int
    delay_end_days: int
    minimum_per_group: int
    created_at: datetime


class RetentionAssignmentIn(BaseModel):
    concept_id: str
    workload_target: int = Field(default=12, ge=1, le=100)


class RetentionAssignmentOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    study_id: str
    concept_id: str
    study_group: str
    workload_target: int
    assigned_at: datetime


class RetentionProbeIn(BaseModel):
    learning_claim_id: str


class RetentionProbeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    assignment_id: str
    evidence_item_id: str
    learning_claim_id: str
    scheduled_for: datetime
    status: str
