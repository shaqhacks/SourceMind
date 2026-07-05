"""SQLAlchemy ORM models for SourceMind."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, TEXT, Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from SourceMind.backend.db.base import Base


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    generation_status: Mapped[str | None] = mapped_column(String, nullable=True)
    generation_progress: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    generation_last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), nullable=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=True
    )

    plan_items: Mapped[list[PlanItem]] = relationship("PlanItem", back_populates="course")
    chapters: Mapped[list[Chapter]] = relationship("Chapter", back_populates="course")
    assets: Mapped[list[Asset]] = relationship("Asset", back_populates="course")
    progress_states: Mapped[list[ProgressState]] = relationship("ProgressState", back_populates="course")
    review_states: Mapped[list[ReviewState]] = relationship("ReviewState", back_populates="course")
    chat_turns: Mapped[list[ChatTurn]] = relationship("ChatTurn", back_populates="course")
    test_attempts: Mapped[list["TestAttempt"]] = relationship("TestAttempt", back_populates="course")


class PlanItem(Base):
    __tablename__ = "plan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(String, ForeignKey("courses.id"), nullable=False)
    section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    objectives: Mapped[list | None] = mapped_column(JSON, nullable=True)
    importance: Mapped[str | None] = mapped_column(String, nullable=True)
    prerequisites: Mapped[list | None] = mapped_column(JSON, nullable=True)
    target_words: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    course: Mapped[Course] = relationship("Course", back_populates="plan_items")


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(String, ForeignKey("courses.id"), nullable=False)
    section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    objectives: Mapped[list | None] = mapped_column(JSON, nullable=True)
    importance: Mapped[str | None] = mapped_column(String, nullable=True)
    source_pages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    body_md: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    quiz: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cards: Mapped[list | None] = mapped_column(JSON, nullable=True)
    word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    lesson_md: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    lesson_status: Mapped[str | None] = mapped_column(String, nullable=True, default="none")
    # ADR-010: None/"toc" = title is authoritative (bookmark-derived or preexisting
    # row, no refinement needed). "placeholder" = deterministic "Pages A-B" title,
    # not yet refined. "refining"/"refined"/"failed" track the one-shot lazy LLM
    # title refinement (see pipeline.service.maybe_refine_title); "failed" is
    # retried on the next claim rather than being a terminal state.
    title_status: Mapped[str | None] = mapped_column(String, nullable=True)

    course: Mapped[Course] = relationship("Course", back_populates="chapters")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    course_id: Mapped[str] = mapped_column(String, ForeignKey("courses.id"), nullable=False)
    path: Mapped[str | None] = mapped_column(String, nullable=True)
    source_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    caption: Mapped[str | None] = mapped_column(String, nullable=True)

    course: Mapped[Course] = relationship("Course", back_populates="assets")


class ProgressState(Base):
    __tablename__ = "progress_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(String, ForeignKey("courses.id"), nullable=False)
    section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    completed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_viewed_at: Mapped[str | None] = mapped_column(String, nullable=True)

    course: Mapped[Course] = relationship("Course", back_populates="progress_states")


class ReviewState(Base):
    __tablename__ = "review_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(String, ForeignKey("courses.id"), nullable=False)
    section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    card_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ease: Mapped[float | None] = mapped_column(Float, nullable=True)
    interval: Mapped[int | None] = mapped_column(Integer, nullable=True)
    due_at: Mapped[str | None] = mapped_column(String, nullable=True)
    reps: Mapped[int | None] = mapped_column(Integer, nullable=True)

    course: Mapped[Course] = relationship("Course", back_populates="review_states")


class ReviewLog(Base):
    __tablename__ = "review_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(String, ForeignKey("courses.id"), nullable=False)
    section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    card_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class ChatTurn(Base):
    __tablename__ = "chat_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(String, ForeignKey("courses.id"), nullable=False)
    section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str | None] = mapped_column(TEXT, nullable=True)
    created_at: Mapped[str | None] = mapped_column(String, nullable=True)
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)

    course: Mapped[Course] = relationship("Course", back_populates="chat_turns")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(String, ForeignKey("courses.id"), nullable=False)
    source_ref: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(TEXT, nullable=False)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)


class TestAttempt(Base):
    __tablename__ = "test_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    course_id: Mapped[str] = mapped_column(String, ForeignKey("courses.id"), nullable=False)
    section_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scope: Mapped[str] = mapped_column(String, nullable=False)   # "section" or "course"
    answers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    correct: Mapped[int] = mapped_column(Integer, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[str | None] = mapped_column(String, nullable=True)

    course: Mapped["Course"] = relationship("Course", back_populates="test_attempts")
