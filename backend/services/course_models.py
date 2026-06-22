from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CourseStatus(str, Enum):
    outline_draft = "outline_draft"
    generating = "generating"
    ready = "ready"
    needs_review = "needs_review"


class GenerationStatus(str, Enum):
    idle = "idle"
    queued = "queued"
    running = "running"
    retry_scheduled = "retry_scheduled"
    succeeded = "succeeded"
    failed = "failed"


class SupportStatus(str, Enum):
    pdf_backed = "pdf_backed"
    course_inference = "course_inference"
    outside_knowledge = "outside_knowledge"


class SourceFile(BaseModel):
    id: str
    filename: str
    order: int


class SourceSpan(BaseModel):
    source_file_id: str
    source_name: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    text: str = ""


class ConceptMastery(BaseModel):
    mastery_percent: float = Field(default=0, ge=0, le=100)
    confidence_history: list[int] = Field(default_factory=list)
    review_interval: int = Field(default=0, ge=0)
    last_score: float | None = Field(default=None, ge=0, le=100)
    failure_streak: int = Field(default=0, ge=0)
    last_reviewed_at: str | None = None
    next_review_at: str | None = None


class Concept(BaseModel):
    id: str
    title: str
    explanation: str = ""
    source_refs: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    mastery: ConceptMastery = Field(default_factory=ConceptMastery)


class CourseCompetency(BaseModel):
    id: str
    title: str
    description: str = ""
    level: int = Field(default=1, ge=1, le=3)
    prerequisite_ids: list[str] = Field(default_factory=list)
    lesson_ids: list[str] = Field(default_factory=list)
    mastery: ConceptMastery = Field(default_factory=ConceptMastery)


class LessonBlock(BaseModel):
    id: str
    kind: Literal["teaching", "source_excerpt", "definition", "worked_example", "common_mistake", "quick_check", "self_explanation"]
    title: str
    body: str
    source_refs: list[str] = Field(default_factory=list)


class WorkedExample(BaseModel):
    id: str
    title: str
    prompt: str
    steps: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class CheckItem(BaseModel):
    id: str
    kind: Literal["short_answer", "multiple_choice", "self_explanation"]
    prompt: str
    expected_answer: str
    choices: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    concept_ids: list[str] = Field(default_factory=list)
    completed: bool = False
    last_score: float | None = Field(default=None, ge=0, le=100)


class QuizItem(BaseModel):
    id: str
    kind: Literal["recall", "application", "explanation", "multiple_choice"]
    prompt: str
    expected_answer: str
    choices: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    concept_ids: list[str] = Field(default_factory=list)


class ChatTurn(BaseModel):
    question: str
    answer: str
    support_status: SupportStatus
    source_refs: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


class SectionLesson(BaseModel):
    id: str
    chapter_id: str
    number: str
    title: str
    order: int
    source_spans: list[SourceSpan] = Field(default_factory=list)
    competency_ids: list[str] = Field(default_factory=list)
    lesson_goal: str = ""
    learning_objectives: list[str] = Field(default_factory=list)
    concepts: list[Concept] = Field(default_factory=list)
    lesson_blocks: list[LessonBlock] = Field(default_factory=list)
    worked_examples: list[WorkedExample] = Field(default_factory=list)
    checks: list[CheckItem] = Field(default_factory=list)
    mastery_quiz: list[QuizItem] = Field(default_factory=list)
    is_assessment_section: bool = False
    assessment_reason: str = ""
    prerequisites: list[str] = Field(default_factory=list)
    completed: bool = False
    status: CourseStatus = CourseStatus.outline_draft
    chat_history: list[ChatTurn] = Field(default_factory=list)


class Chapter(BaseModel):
    id: str
    number: str
    title: str
    order: int
    sections: list[SectionLesson] = Field(default_factory=list)


class CourseGenerationProgress(BaseModel):
    status: GenerationStatus = GenerationStatus.idle
    total_sections: int = Field(default=0, ge=0)
    completed_sections: int = Field(default=0, ge=0)
    failed_sections: int = Field(default=0, ge=0)
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=5, ge=1)
    next_retry_at: str | None = None
    last_error: str | None = None
    started_at: str | None = None
    updated_at: str | None = None
    finished_at: str | None = None


class CourseDocument(BaseModel):
    schema_version: int = Field(default=1, ge=1)
    course_id: str
    title: str
    status: CourseStatus = CourseStatus.outline_draft
    source_files: list[SourceFile] = Field(default_factory=list)
    competencies: list[CourseCompetency] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    generation: CourseGenerationProgress = Field(default_factory=CourseGenerationProgress)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    archived_at: str | None = None
    notes: str = ""

    @field_validator("course_id", "title")
    @classmethod
    def require_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value cannot be empty")
        return value

    def all_sections(self) -> list[SectionLesson]:
        return [section for chapter in self.chapters for section in chapter.sections]

    def all_concepts(self) -> list[Concept]:
        return [concept for section in self.all_sections() for concept in section.concepts]

    def competency_by_id(self, competency_id: str) -> CourseCompetency | None:
        return next((competency for competency in self.competencies if competency.id == competency_id), None)
