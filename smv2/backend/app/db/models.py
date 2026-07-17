from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm.attributes import NO_VALUE


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    """Attach UTC tzinfo to a naive datetime.

    SQLite drops tzinfo on write and returns naive datetimes on read, so any
    lease/timestamp comparison must normalize through this first or aware
    vs. naive comparisons will raise.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    type: Mapped[str] = mapped_column(String, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String, index=True, nullable=False, default="queued")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    progress: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String, nullable=False)
    stored_path: Mapped[str] = mapped_column(String, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="stored")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 'none' | 'converting' | 'ready' | 'failed' — pdf2htmlEX per-page HTML
    # conversion state (ADR-020), a post-ingest enhancement job, separate
    # from `status` (the PDF extraction state above).
    html_status: Mapped[str] = mapped_column(String, nullable=False, default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class Section(Base):
    """A chapter/section of source text.

    body_md is the immutable source text — enforced both by the
    sections_body_md_immutable SQLite trigger (migration 0002) and by the
    'set' event listener below, which raises before a persisted instance's
    body_md is reassigned to a different value. lesson_md is the only
    column generation is ever allowed to write.
    """

    __tablename__ = "sections"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    # Which uploaded PDF this section's text came from — lets the reader
    # offer an original-PDF page view. NULL for sections created before this
    # column existed (backfills only on the next re-ingest, never
    # retroactively). page_start/page_end are already per-asset 1-based
    # page numbers (not course-wide), so pdf.js can use them directly as
    # page numbers for THIS asset — never re-derive or re-offset them.
    asset_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    lesson_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    lesson_status: Mapped[str] = mapped_column(String, nullable=False, default="none")
    lesson_model: Mapped[str | None] = mapped_column(String, nullable=True)
    lesson_prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    extractor_version: Mapped[str | None] = mapped_column(String, nullable=True)
    # 'content' | 'practice' | 'answers' — deterministic, title-only
    # classification (ADR-017). chapter_label is the exact title of the
    # chapter-marker section this section is grouped under, or NULL if the
    # course has no detected chapter markers at all ("Front matter" group,
    # client-side label).
    kind: Mapped[str] = mapped_column(String, nullable=False, default="content")
    chapter_label: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


@event.listens_for(Section.body_md, "set", retval=False)
def _guard_body_md_immutable(target: Section, value: str, oldvalue: Any, initiator: Any) -> None:
    if oldvalue is NO_VALUE:
        return
    if sa_inspect(target).persistent and value != oldvalue:
        raise ValueError("body_md is immutable once a section is persisted")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    section_id: Mapped[str] = mapped_column(
        String, ForeignKey("sections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Nullable by law: retrieval must skip chunks with no embedding rather
    # than assume every chunk has one.
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    source_ref: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Card(Base):
    __tablename__ = "cards"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    section_id: Mapped[str] = mapped_column(
        String, ForeignKey("sections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    front_md: Mapped[str] = mapped_column(Text, nullable=False)
    back_md: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    # 'generated' | 'user' (ADR-023) — user-origin cards (newly authored, or
    # the result of editing a generated card's content) are excluded from
    # card_generation's regenerate diff, so a re-generation never touches
    # them.
    origin: Mapped[str] = mapped_column(String, nullable=False, default="generated")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class ReviewState(Base):
    __tablename__ = "review_states"

    card_id: Mapped[str] = mapped_column(
        String, ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True
    )
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    due_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    interval_days: Mapped[float] = mapped_column(Float, nullable=False)
    ease: Mapped[float] = mapped_column(Float, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lapses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_grade: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    card_id: Mapped[str] = mapped_column(
        String, ForeignKey("cards.id", ondelete="CASCADE"), index=True, nullable=False
    )
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    graded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ProgressState(Base):
    """Per-course reading position.

    section_id is ON DELETE SET NULL (not CASCADE): losing the section the
    reader was on must not delete the course's resume row entirely, just
    clear the pointer.
    """

    __tablename__ = "progress_states"

    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True
    )
    section_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sections.id", ondelete="SET NULL"), nullable=True
    )
    scroll_pos: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class ChatTurn(Base):
    __tablename__ = "chat_turns"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Highlight(Base):
    """A user-created highlight/note anchored to a section's body_md by
    text quote (exact/prefix/suffix/occurrence), never by DOM position or
    char offset — the same selection must be locatable in more than one
    rendering of the text (markdown DOM, pdf.js text layer). The anchor is
    opaque to the backend; the frontend matcher owns its semantics.
    Wiped on re-ingest (REPLACED bucket, ADR-024): re-uploading a course's
    PDF deletes its highlights — the upload UI must warn.
    page is 0-based per-asset storage, converted at the service boundary
    like Section.page_start.
    """

    __tablename__ = "highlights"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    section_id: Mapped[str] = mapped_column(
        String, ForeignKey("sections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    exact: Mapped[str] = mapped_column(Text, nullable=False)
    prefix: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    suffix: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    occurrence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    color: Mapped[str] = mapped_column(String, nullable=False, default="yellow")
    note_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class Test(Base):
    """A generated quiz deck — the persisted questions, generated once.
    Retaking a test (ADR-022) creates a new TestAttempt against this SAME
    Test, zero further LLM calls; only the attempt's answers/score/results
    differ between retakes.
    """

    __tablename__ = "tests"
    __test__ = False  # not a pytest test class, despite the name

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Set only for a chapter-scoped test (POST .../tests with chapter_label);
    # NULL for the pre-existing explicit-section_ids / whole-course modes.
    chapter_label: Mapped[str | None] = mapped_column(String, nullable=True)
    # Only ever set in the narrow single-section-quiz mode (see
    # quiz_generation.py) — used as a missed-question card-attribution
    # fallback (tests_service._resolve_missed_card_section_id), same
    # semantics as the pre-split TestAttempt.section_id it replaces.
    section_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sections.id", ondelete="SET NULL"), nullable=True
    )
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class TestAttempt(Base):
    """One attempt at a Test's persisted questions. Deliberately carries no
    copy of the questions themselves (Test.questions is the single source)
    — only this attempt's own answers/results/score, so retaking a test
    (a new TestAttempt against the same Test) never re-touches the deck.
    answers/results are NULL until submitted, same "None = not graded yet"
    convention TestAttempt.score already used pre-split.
    """

    __tablename__ = "test_attempts"
    __test__ = False  # not a pytest test class, despite the name

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    test_id: Mapped[str] = mapped_column(
        String, ForeignKey("tests.id", ondelete="CASCADE"), index=True, nullable=False
    )
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    answers: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    results: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class Concept(Base):
    __tablename__ = "concepts"
    __table_args__ = (UniqueConstraint("course_id", "slug", name="uq_concepts_course_slug"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    slug: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    chapter_label: Mapped[str | None] = mapped_column(String, nullable=True)
    section_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sections.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class PracticeQuestion(Base):
    __tablename__ = "practice_questions"
    __table_args__ = (
        UniqueConstraint(
            "course_id",
            "section_id",
            "source_fingerprint",
            name="uq_practice_questions_source",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    chapter_label: Mapped[str | None] = mapped_column(String, nullable=True)
    section_id: Mapped[str] = mapped_column(
        String, ForeignKey("sections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    concept_id: Mapped[str] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    source_asset_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
    )
    source_page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    problem_number: Mapped[str] = mapped_column(String, nullable=False)
    source_ref: Mapped[str] = mapped_column(String, nullable=False)
    answer_section_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sections.id", ondelete="SET NULL"), nullable=True
    )
    answer_source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    stem_md: Mapped[str] = mapped_column(Text, nullable=False)
    choices: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    correct_index: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation_md: Mapped[str] = mapped_column(Text, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    extraction_version: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="ready")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class PracticeExtractionRun(Base):
    __tablename__ = "practice_extraction_runs"
    __table_args__ = (
        UniqueConstraint(
            "course_id",
            "section_id",
            "input_fingerprint",
            name="uq_practice_runs_input",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    section_id: Mapped[str] = mapped_column(
        String, ForeignKey("sections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")
    job_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    input_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    question_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class PracticeAnswer(Base):
    __tablename__ = "practice_answers"
    __table_args__ = (
        UniqueConstraint(
            "learner_key",
            "question_id",
            name="uq_practice_answers_learner_question",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question_id: Mapped[str] = mapped_column(
        String, ForeignKey("practice_questions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    learner_key: Mapped[str] = mapped_column(String, index=True, nullable=False)
    selected_index: Mapped[int] = mapped_column(Integer, nullable=False)
    correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    points_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    answered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class ConceptMastery(Base):
    __tablename__ = "concept_masteries"

    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), primary_key=True
    )
    concept_id: Mapped[str] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="CASCADE"), primary_key=True
    )
    learner_key: Mapped[str] = mapped_column(String, primary_key=True)
    points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class ConceptMasteryEvent(Base):
    __tablename__ = "concept_mastery_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    concept_id: Mapped[str] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    question_id: Mapped[str] = mapped_column(
        String, ForeignKey("practice_questions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    practice_answer_id: Mapped[str] = mapped_column(
        String, ForeignKey("practice_answers.id", ondelete="CASCADE"), index=True, nullable=False
    )
    learner_key: Mapped[str] = mapped_column(String, index=True, nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class LlmCall(Base):
    """Append-only ledger of every LLM call made, for cost/debug visibility.

    course_id is ON DELETE SET NULL: deleting a course must not erase spend
    history, it just anonymizes which course the call was for.
    """

    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    course_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("courses.id", ondelete="SET NULL"), index=True, nullable=True
    )
