from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
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


class TestAttempt(Base):
    __tablename__ = "test_attempts"
    __test__ = False  # not a pytest test class, despite the name

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    section_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("sections.id", ondelete="SET NULL"), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    # Set only for a chapter-scoped test (POST .../tests with chapter_label);
    # NULL for the pre-existing explicit-section_ids / whole-course modes.
    chapter_label: Mapped[str | None] = mapped_column(String, nullable=True)
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
