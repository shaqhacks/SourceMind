from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
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


class LearnerProfile(Base):
    __tablename__ = "learner_profiles"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class CourseLearningProfile(Base):
    __tablename__ = "course_learning_profiles"
    __table_args__ = (
        UniqueConstraint(
            "learner_id", "course_id", name="uq_course_learning_profiles_learner_course"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    learner_id: Mapped[str] = mapped_column(
        String, ForeignKey("learner_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
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
    __table_args__ = (
        UniqueConstraint(
            "course_learning_profile_id", "card_id", name="uq_review_states_profile_card"
        ),
    )

    course_learning_profile_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("course_learning_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
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
    course_learning_profile_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("course_learning_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
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
    # source = anchored in body_md markdown DOM; pdf = anchored in the PDF
    # text layer; the two never cross-map.
    surface: Mapped[str] = mapped_column(String, nullable=False, default="source")
    note_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class Note(Base):
    """A free-standing margin note anchored to a vertical position on a PDF
    page (surface="pdf"), not to selected text — the coordinate equivalent of
    Highlight, for annotating a spot with no highlightable passage. anchor_y
    is a 0..1 top-origin fraction of the page height, so it survives the page
    re-rendering at any width. page is 0-based in the DB / 1-based at the API,
    the same single-conversion rule as Highlight. Wiped on re-ingest (ADR-024).
    """

    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    section_id: Mapped[str] = mapped_column(
        String, ForeignKey("sections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    surface: Mapped[str] = mapped_column(String, nullable=False, default="pdf")
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor_y: Mapped[float] = mapped_column(Float, nullable=False)
    note_md: Mapped[str] = mapped_column(Text, nullable=False)
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
    course_learning_profile_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("course_learning_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
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
    merged_into_concept_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class CurriculumVersion(Base):
    __tablename__ = "curriculum_versions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'superseded')",
            name="ck_curriculum_versions_status",
        ),
        CheckConstraint(
            "is_current = 0 OR status = 'published'",
            name="ck_curriculum_versions_current_published",
        ),
        Index(
            "uq_curriculum_versions_current_course",
            "course_id",
            unique=True,
            sqlite_where=text("is_current = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parent_version_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("curriculum_versions.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ConceptRevision(Base):
    __tablename__ = "concept_revisions"
    __table_args__ = (
        UniqueConstraint(
            "curriculum_version_id", "concept_id", name="uq_concept_revisions_version_concept"
        ),
        CheckConstraint(
            "review_state IN ('unverified', 'verified', 'rejected')",
            name="ck_concept_revisions_review_state",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    curriculum_version_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("curriculum_versions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    concept_id: Mapped[str] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    label: Mapped[str] = mapped_column(String, nullable=False)
    description_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    chapter_label: Mapped[str | None] = mapped_column(String, nullable=True)
    review_state: Mapped[str] = mapped_column(String, nullable=False, default="unverified")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class LearningClaim(Base):
    __tablename__ = "learning_claims"
    __table_args__ = (
        UniqueConstraint("course_id", "stable_key", name="uq_learning_claims_course_key"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    concept_id: Mapped[str] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    stable_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class LearningClaimRevision(Base):
    __tablename__ = "learning_claim_revisions"
    __table_args__ = (
        UniqueConstraint(
            "curriculum_version_id",
            "learning_claim_id",
            name="uq_learning_claim_revisions_version_claim",
        ),
        CheckConstraint(
            "review_state IN ('unverified', 'verified', 'rejected')",
            name="ck_learning_claim_revisions_review_state",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    curriculum_version_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("curriculum_versions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    learning_claim_id: Mapped[str] = mapped_column(
        String, ForeignKey("learning_claims.id", ondelete="CASCADE"), index=True, nullable=False
    )
    concept_id: Mapped[str] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    success_criteria_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    cognitive_demand: Mapped[str | None] = mapped_column(String, nullable=True)
    review_state: Mapped[str] = mapped_column(String, nullable=False, default="unverified")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class ConceptRelation(Base):
    __tablename__ = "concept_relations"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('is_part_of', 'requires', 'recommended_before', "
            "'develops_into', 'related_to', 'equivalent_to', 'aligns_to_standard')",
            name="ck_concept_relations_kind",
        ),
        CheckConstraint(
            "review_state IN ('unverified', 'verified', 'rejected')",
            name="ck_concept_relations_review_state",
        ),
        UniqueConstraint(
            "curriculum_version_id",
            "from_concept_id",
            "to_concept_id",
            "kind",
            name="uq_concept_relations_version_pair_kind",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    curriculum_version_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("curriculum_versions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    from_concept_id: Mapped[str] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    to_concept_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="CASCADE"), index=True, nullable=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False)
    external_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_state: Mapped[str] = mapped_column(String, nullable=False, default="unverified")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class ConceptSourceLink(Base):
    __tablename__ = "concept_source_links"
    __table_args__ = (
        CheckConstraint(
            "review_state IN ('unverified', 'verified', 'rejected')",
            name="ck_concept_source_links_review_state",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    curriculum_version_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("curriculum_versions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    concept_id: Mapped[str] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    learning_claim_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("learning_claims.id", ondelete="CASCADE"), index=True, nullable=True
    )
    section_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sections.id", ondelete="SET NULL"), index=True, nullable=True
    )
    source_ref: Mapped[str] = mapped_column(String, nullable=False)
    excerpt_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_state: Mapped[str] = mapped_column(String, nullable=False, default="unverified")
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class EvidenceItem(Base):
    __tablename__ = "evidence_items"
    __table_args__ = (
        CheckConstraint(
            "item_type IN ('quiz_question', 'practice_question', 'flashcard')",
            name="ck_evidence_items_type",
        ),
        CheckConstraint(
            "mapping_status IN ('mapped', 'legacy_unmapped')",
            name="ck_evidence_items_mapping_status",
        ),
        UniqueConstraint(
            "item_type",
            "source_record_id",
            "source_index",
            "content_fingerprint",
            name="uq_evidence_items_source_snapshot",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    item_type: Mapped[str] = mapped_column(String, nullable=False)
    source_record_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    source_index: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
    mapping_status: Mapped[str] = mapped_column(
        String, nullable=False, default="legacy_unmapped"
    )
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class EvidenceItemConceptLink(Base):
    __tablename__ = "evidence_item_concept_links"
    __table_args__ = (
        CheckConstraint(
            "role IN ('primary', 'supporting', 'prerequisite')",
            name="ck_evidence_item_concept_links_role",
        ),
        CheckConstraint(
            "review_state IN ('unverified', 'verified', 'rejected')",
            name="ck_evidence_item_concept_links_review_state",
        ),
        UniqueConstraint(
            "evidence_item_id",
            "curriculum_version_id",
            "learning_claim_id",
            "role",
            name="uq_evidence_item_concept_links_mapping",
        ),
        Index(
            "uq_evidence_item_concept_links_primary",
            "evidence_item_id",
            unique=True,
            sqlite_where=text("role = 'primary' AND review_state != 'rejected'"),
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    evidence_item_id: Mapped[str] = mapped_column(
        String, ForeignKey("evidence_items.id", ondelete="CASCADE"), index=True, nullable=False
    )
    curriculum_version_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("curriculum_versions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    learning_claim_id: Mapped[str] = mapped_column(
        String, ForeignKey("learning_claims.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    cognitive_demand: Mapped[str | None] = mapped_column(String, nullable=True)
    authored_difficulty_band: Mapped[str | None] = mapped_column(String, nullable=True)
    mapping_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    review_state: Mapped[str] = mapped_column(String, nullable=False, default="unverified")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class LearnerEvidenceEvent(Base):
    __tablename__ = "learner_evidence_events"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('practice', 'quiz', 'review')",
            name="ck_learner_evidence_events_channel",
        ),
        CheckConstraint(
            "normalized_outcome >= 0 AND normalized_outcome <= 1",
            name="ck_learner_evidence_events_outcome",
        ),
        CheckConstraint(
            "spacing_seconds IS NULL OR spacing_seconds >= 0",
            name="ck_learner_evidence_events_spacing",
        ),
        UniqueConstraint("source_event_key", name="uq_learner_evidence_events_source"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    course_learning_profile_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("course_learning_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    evidence_item_id: Mapped[str] = mapped_column(
        String, ForeignKey("evidence_items.id", ondelete="CASCADE"), index=True, nullable=False
    )
    evidence_mapping_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("evidence_item_concept_links.id", ondelete="SET NULL"),
        nullable=True,
    )
    learning_claim_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("learning_claims.id", ondelete="SET NULL"), index=True, nullable=True
    )
    curriculum_version_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("curriculum_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    channel: Mapped[str] = mapped_column(String, nullable=False)
    normalized_outcome: Mapped[float] = mapped_column(Float, nullable=False)
    raw_result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempt_id: Mapped[str | None] = mapped_column(String, nullable=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_event_key: Mapped[str] = mapped_column(String, nullable=False)
    spacing_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    model_version: Mapped[str] = mapped_column(String, nullable=False, default="evidence-v1")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class LearnerConceptState(Base):
    __tablename__ = "learner_concept_states"
    __table_args__ = (
        CheckConstraint(
            "state_scope IN ('claim', 'concept')",
            name="ck_learner_concept_states_scope",
        ),
        CheckConstraint(
            "status IN ('insufficient_evidence', 'likely_struggling', 'building', "
            "'watch', 'retained')",
            name="ck_learner_concept_states_status",
        ),
        UniqueConstraint(
            "course_learning_profile_id",
            "curriculum_version_id",
            "state_key",
            "model_version",
            name="uq_learner_concept_states_projection",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    course_learning_profile_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("course_learning_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    curriculum_version_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("curriculum_versions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    concept_id: Mapped[str] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    learning_claim_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("learning_claims.id", ondelete="CASCADE"), index=True, nullable=True
    )
    state_scope: Mapped[str] = mapped_column(String, nullable=False)
    state_key: Mapped[str] = mapped_column(String, nullable=False)
    readiness_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    quiz_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    lower_bound: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_bound: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty: Mapped[float | None] = mapped_column(Float, nullable=True)
    effective_evidence_count: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    distinct_item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    distinct_session_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trend: Mapped[str] = mapped_column(String, nullable=False, default="unknown")
    status: Mapped[str] = mapped_column(
        String, nullable=False, default="insufficient_evidence"
    )
    forgetting_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    last_evidence_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    calculated_through: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class ShadowLearnerPrediction(Base):
    __tablename__ = "shadow_learner_predictions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('predicted', 'insufficient_data', 'disabled')",
            name="ck_shadow_learner_predictions_status",
        ),
        UniqueConstraint(
            "course_learning_profile_id",
            "learning_claim_id",
            "model_name",
            "model_version",
            "evidence_snapshot_hash",
            name="uq_shadow_learner_predictions_snapshot",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    course_learning_profile_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("course_learning_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    curriculum_version_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("curriculum_versions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    learning_claim_id: Mapped[str] = mapped_column(
        String, ForeignKey("learning_claims.id", ondelete="CASCADE"), index=True, nullable=False
    )
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    predicted_probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_snapshot_hash: Mapped[str] = mapped_column(String, nullable=False)
    training_cutoff: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    feature_schema_version: Mapped[str] = mapped_column(String, nullable=False)
    prediction_horizon: Mapped[str] = mapped_column(String, nullable=False)
    target_definition: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class DiagnosticJudgment(Base):
    __tablename__ = "diagnostic_judgments"
    __table_args__ = (
        CheckConstraint(
            "judgment IN ('insufficient', 'not_struggling', 'uncertain', 'likely_struggling')",
            name="ck_diagnostic_judgments_judgment",
        ),
        CheckConstraint(
            "disagreement_reason IS NULL OR disagreement_reason IN "
            "('model_estimate', 'item_mapping', 'concept_granularity', "
            "'insufficient_student_evidence', 'instructor_disagreement')",
            name="ck_diagnostic_judgments_reason",
        ),
        UniqueConstraint(
            "course_learning_profile_id",
            "curriculum_version_id",
            "concept_id",
            "reviewer_key",
            name="uq_diagnostic_judgments_blind_review",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    course_learning_profile_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("course_learning_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    curriculum_version_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("curriculum_versions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    concept_id: Mapped[str] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    reviewer_key: Mapped[str] = mapped_column(String, nullable=False, default="local-owner")
    judgment: Mapped[str] = mapped_column(String, nullable=False)
    disagreement_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    notes_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_state: Mapped[str] = mapped_column(String, nullable=False)
    readiness_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    state_calculated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    agreement: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class RetentionStudy(Base):
    __tablename__ = "retention_studies"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'closed')",
            name="ck_retention_studies_status",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    assignment_seed: Mapped[str] = mapped_column(String, nullable=False)
    protocol_version: Mapped[str] = mapped_column(String, nullable=False, default="retention-v1")
    delay_start_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    delay_end_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14)
    minimum_per_group: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class RetentionAssignment(Base):
    __tablename__ = "retention_assignments"
    __table_args__ = (
        CheckConstraint(
            "study_group IN ('adaptive_targeted', 'baseline_review')",
            name="ck_retention_assignments_group",
        ),
        UniqueConstraint(
            "study_id",
            "course_learning_profile_id",
            "concept_id",
            name="uq_retention_assignments_pair",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    study_id: Mapped[str] = mapped_column(
        String, ForeignKey("retention_studies.id", ondelete="CASCADE"), index=True, nullable=False
    )
    course_learning_profile_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("course_learning_profiles.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    concept_id: Mapped[str] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    study_group: Mapped[str] = mapped_column(String, nullable=False)
    workload_target: Mapped[int] = mapped_column(Integer, nullable=False)
    assignment_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class RetentionProbe(Base):
    __tablename__ = "retention_probes"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'completed', 'missed', 'cancelled')",
            name="ck_retention_probes_status",
        ),
        UniqueConstraint(
            "assignment_id", "evidence_item_id", name="uq_retention_probes_item"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    assignment_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("retention_assignments.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    evidence_item_id: Mapped[str] = mapped_column(
        String, ForeignKey("evidence_items.id", ondelete="CASCADE"), index=True, nullable=False
    )
    learning_claim_id: Mapped[str] = mapped_column(
        String, ForeignKey("learning_claims.id", ondelete="CASCADE"), index=True, nullable=False
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="scheduled")
    outcome_event_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("learner_evidence_events.id", ondelete="SET NULL"), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class ConceptEdge(Base):
    """A prerequisite edge between two concepts: from must be learned before
    to. Directed, course-scoped. Wiped on re-ingest — concepts themselves
    are wiped and regenerated, so any edge referencing them would otherwise
    dangle.
    """

    __tablename__ = "concept_edges"
    __table_args__ = (
        UniqueConstraint(
            "course_id", "from_concept_id", "to_concept_id", name="uq_concept_edges"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    from_concept_id: Mapped[str] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    to_concept_id: Mapped[str] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class ConceptSectionLink(Base):
    """Where a concept is taught. Concept.section_id stays the "introduced
    here" pointer; this table holds every section a concept is covered in
    (including re-appearances later in the course), ordered by rank within
    a concept. Wiped on re-ingest along with the concepts it references.
    """

    __tablename__ = "concept_section_links"
    __table_args__ = (
        UniqueConstraint("concept_id", "section_id", name="uq_concept_section_links"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    concept_id: Mapped[str] = mapped_column(
        String, ForeignKey("concepts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    section_id: Mapped[str] = mapped_column(
        String, ForeignKey("sections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    relevance_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


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
