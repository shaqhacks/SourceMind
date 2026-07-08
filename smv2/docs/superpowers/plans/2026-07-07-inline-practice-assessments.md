# Inline Practice Assessments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build lazy textbook-backed inline multiple-choice practice assessments with immediate server-side grading and per-question concept mastery updates.

**Architecture:** Add dedicated practice assessment tables, services, router, and extraction job. Cached `PracticeQuestion` rows are global per course section, while `PracticeAnswer` and concept mastery rows are learner-specific through an opaque learner cookie until real auth exists. The frontend renders inline assessment cards for practice sections and removes the pre-answer answer-key disclosure from the learner flow.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, existing job worker, existing LLM provider/prompt loader, Pydantic, Next.js/React, openapi-fetch, Vitest, Pytest.

---

## File Map

Backend data layer:

- Modify `backend/app/db/models.py`: add `Concept`, `PracticeQuestion`, `PracticeExtractionRun`, `PracticeAnswer`, `ConceptMastery`, and `ConceptMasteryEvent`.
- Modify `backend/app/db/registry.py`: register the new FK-bearing models in `REPLACED_ON_REINGEST`.
- Create `backend/app/db/migrations/versions/0009_inline_practice_assessments.py`: create the new tables and indexes.

Backend service and extraction:

- Create `backend/app/services/practice_service.py`: lazy status lookup, run creation, learner key creation, answer grading, mastery updates.
- Create `backend/app/pipeline/practice_extraction.py`: textbook-backed extraction job, response parser, question persistence.
- Create `backend/prompts/v3/practice_assessment.md`: LLM prompt for structuring practice problems, mapping answer-key entries, assigning concepts, and generating choices.
- Modify `backend/app/jobs/registry.py`: register `generate_practice_assessment`.

Backend API:

- Modify `backend/app/schemas.py`: add practice assessment request/response models.
- Create `backend/app/routers/practice.py`: add GET section assessment and POST answer endpoints.
- Modify `backend/app/main.py`: include the practice router.
- Modify `backend/tests/conftest.py`: add `app.pipeline.practice_extraction.get_provider` to provider patch targets.

Backend tests:

- Create `backend/tests/test_practice_models.py`: model/migration/registry behavior.
- Create `backend/tests/test_practice_service.py`: lazy extraction, duplicate run reuse, grading, duplicate answers, mastery.
- Create `backend/tests/test_practice_extraction.py`: parser, answer-key mapping, low-confidence exclusion.
- Create `backend/tests/test_practice_api.py`: HTTP responses, redaction, cookie, course isolation.
- Modify `backend/tests/test_course_delete_cascade.py`: course delete removes practice assessment rows.

Frontend API:

- Modify `openapi.json`: regenerated from backend.
- Modify `frontend/lib/api/schema.d.ts`: regenerated from OpenAPI.
- Modify `frontend/lib/api/client.ts`: export practice types and helper functions.

Frontend UI:

- Create `frontend/components/chapter/InlinePracticeAssessment.tsx`: section-level inline multiple-choice UI.
- Modify `frontend/components/chapter/ChapterTestClient.tsx`: render inline assessments for practice sections and remove the answer-key disclosure from the normal learner path.
- Modify `frontend/__tests__/chapter-test-client.test.tsx`: update expectations around practice rendering and answer-key visibility.
- Create `frontend/__tests__/inline-practice-assessment.test.tsx`: focused UI tests for generating, ready, answer reveal, and duplicate answer lock.

## Task 1: Add Practice Assessment Tables

**Files:**

- Modify: `backend/app/db/models.py`
- Modify: `backend/app/db/registry.py`
- Create: `backend/app/db/migrations/versions/0009_inline_practice_assessments.py`
- Create: `backend/tests/test_practice_models.py`
- Modify: `backend/tests/test_course_delete_cascade.py`

- [ ] **Step 1: Write model and registry tests first**

Create `backend/tests/test_practice_models.py`:

```python
from __future__ import annotations

import uuid

from app.db.engine import get_session
from app.db.models import (
    Concept,
    ConceptMastery,
    ConceptMasteryEvent,
    Course,
    PracticeAnswer,
    PracticeExtractionRun,
    PracticeQuestion,
    Section,
)
from app.db.registry import REPLACED_ON_REINGEST


def test_practice_models_are_registered_for_reingest(client):
    registered = {model.__name__ for model in REPLACED_ON_REINGEST}
    assert {
        "Concept",
        "PracticeQuestion",
        "PracticeExtractionRun",
        "PracticeAnswer",
        "ConceptMastery",
        "ConceptMasteryEvent",
    }.issubset(registered)


def test_practice_question_unique_fingerprint_per_section(client):
    session = get_session()
    try:
        course = Course(title="Practice Course")
        session.add(course)
        session.flush()
        section = Section(
            id="practice-section",
            course_id=course.id,
            order_index=1,
            title="0.2 Practice - Fractions",
            body_md="1. Simplify 42/12",
            content_hash="practice-hash",
            kind="practice",
            chapter_label="Chapter 0 : Pre-Algebra",
        )
        concept = Concept(
            id=str(uuid.uuid4()),
            course_id=course.id,
            slug="fractions.simplify",
            label="Simplifying Fractions",
            chapter_label=section.chapter_label,
            section_id=section.id,
        )
        session.add_all([section, concept])
        session.flush()
        first = PracticeQuestion(
            course_id=course.id,
            chapter_label=section.chapter_label,
            section_id=section.id,
            concept_id=concept.id,
            problem_number="1",
            source_ref="0.2 Practice - Fractions #1",
            stem_md="Simplify $42/12$.",
            choices=["$7/2$", "$2/7$", "$3/4$", "$14/3$"],
            correct_index=0,
            explanation_md="$42/12 = 7/2$.",
            source_fingerprint="fingerprint-1",
            extraction_version="v3",
            confidence=0.99,
            status="ready",
        )
        duplicate = PracticeQuestion(
            course_id=course.id,
            chapter_label=section.chapter_label,
            section_id=section.id,
            concept_id=concept.id,
            problem_number="1",
            source_ref="0.2 Practice - Fractions #1 duplicate",
            stem_md="Simplify $42/12$.",
            choices=["$7/2$", "$2/7$", "$3/4$", "$14/3$"],
            correct_index=0,
            explanation_md="$42/12 = 7/2$.",
            source_fingerprint="fingerprint-1",
            extraction_version="v3",
            confidence=0.99,
            status="ready",
        )
        session.add(first)
        session.commit()
        session.add(duplicate)
        try:
            session.commit()
        except Exception:
            session.rollback()
        else:
            raise AssertionError("duplicate source_fingerprint should be rejected")
    finally:
        session.close()
```

Run:

```bash
cd backend
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_practice_models.py -p no:cacheprovider
```

Expected: FAIL because the models and migration do not exist yet.

- [ ] **Step 2: Add ORM models**

In `backend/app/db/models.py`, add the six model classes after `TestAttempt` and before `LlmCall` so assessment models stay near quiz models:

```python
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
        UniqueConstraint("course_id", "section_id", "source_fingerprint", name="uq_practice_questions_source"),
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
```

Add the remaining four classes using the fields from the design spec:

```python
class PracticeExtractionRun(Base):
    __tablename__ = "practice_extraction_runs"
    __table_args__ = (
        UniqueConstraint("course_id", "section_id", "input_fingerprint", name="uq_practice_runs_input"),
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
        UniqueConstraint("learner_key", "question_id", name="uq_practice_answers_learner_question"),
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
```

Also add `Boolean` and `UniqueConstraint` to the SQLAlchemy imports. Define `ConceptMastery` with composite primary key and `ConceptMasteryEvent` with event fields exactly from the spec.

- [ ] **Step 3: Add the Alembic migration**

Create `backend/app/db/migrations/versions/0009_inline_practice_assessments.py` with `down_revision = "0008_card_origin"`. Use `op.create_table` for each new table and `op.create_index` for indexed columns. Include named unique constraints:

```python
sa.UniqueConstraint("course_id", "slug", name="uq_concepts_course_slug")
sa.UniqueConstraint("course_id", "section_id", "source_fingerprint", name="uq_practice_questions_source")
sa.UniqueConstraint("course_id", "section_id", "input_fingerprint", name="uq_practice_runs_input")
sa.UniqueConstraint("learner_key", "question_id", name="uq_practice_answers_learner_question")
```

Downgrade order must drop child tables first:

```python
op.drop_table("concept_mastery_events")
op.drop_table("concept_masteries")
op.drop_table("practice_answers")
op.drop_table("practice_extraction_runs")
op.drop_table("practice_questions")
op.drop_table("concepts")
```

- [ ] **Step 4: Register the models for re-ingest**

In `backend/app/db/registry.py`, import the six new models and append them to `REPLACED_ON_REINGEST`.

Use this ordering so child rows are deleted before parent rows in any explicit delete path:

```python
REPLACED_ON_REINGEST = [
    Asset,
    Section,
    Chunk,
    Card,
    ChatTurn,
    Test,
    TestAttempt,
    PracticeAnswer,
    ConceptMasteryEvent,
    ConceptMastery,
    PracticeQuestion,
    PracticeExtractionRun,
    Concept,
]
```

- [ ] **Step 5: Extend course delete cascade test**

In `backend/tests/test_course_delete_cascade.py`, add rows for each new model before deleting the course, then assert each count is zero afterward. Keep the rows minimal: one concept, one question, one extraction run, one answer, one mastery, one event.

- [ ] **Step 6: Extend re-ingest destructive cleanup**

In `backend/app/pipeline/ingest.py`, import the new models and explicitly delete course-scoped practice assessment rows before section diffing. Use child-to-parent order:

```python
session.query(PracticeAnswer).filter(PracticeAnswer.course_id == course_id).delete()
session.query(ConceptMasteryEvent).filter(ConceptMasteryEvent.course_id == course_id).delete()
session.query(ConceptMastery).filter(ConceptMastery.course_id == course_id).delete()
session.query(PracticeQuestion).filter(PracticeQuestion.course_id == course_id).delete()
session.query(PracticeExtractionRun).filter(PracticeExtractionRun.course_id == course_id).delete()
session.query(Concept).filter(Concept.course_id == course_id).delete()
```

Add a test to `backend/tests/test_ingest_pipeline.py` or a new `backend/tests/test_practice_reingest.py` that seeds a course with one row in each practice assessment table, runs re-ingest, and asserts those rows are gone.

- [ ] **Step 7: Run backend model tests**

Run:

```bash
cd backend
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_practice_models.py tests/test_course_delete_cascade.py tests/test_architecture.py tests/test_practice_reingest.py -p no:cacheprovider
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/db/models.py backend/app/db/registry.py backend/app/db/migrations/versions/0009_inline_practice_assessments.py backend/app/pipeline/ingest.py backend/tests/test_practice_models.py backend/tests/test_course_delete_cascade.py backend/tests/test_practice_reingest.py
git commit -m "feat: add practice assessment models"
```

## Task 2: Add Lazy Practice Assessment Service and API State

**Files:**

- Modify: `backend/app/schemas.py`
- Create: `backend/app/services/practice_service.py`
- Create: `backend/app/routers/practice.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_practice_api.py`
- Create: `backend/tests/test_practice_service.py`

- [ ] **Step 1: Write failing API tests for lazy state**

Create `backend/tests/test_practice_api.py`:

```python
from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Course, Section


def _course_with_practice_section() -> tuple[str, str]:
    session = get_session()
    try:
        course = Course(title="Practice API Course")
        session.add(course)
        session.flush()
        section = Section(
            id="practice-api-section",
            course_id=course.id,
            order_index=1,
            title="0.2 Practice - Fractions",
            body_md="1. Simplify 42/12",
            content_hash="practice-api-hash",
            kind="practice",
            chapter_label="Chapter 0 : Pre-Algebra",
        )
        answers = Section(
            id="answers-api-section",
            course_id=course.id,
            order_index=2,
            title="Chapter 0 Answers",
            body_md="1. 7/2",
            content_hash="answers-api-hash",
            kind="answers",
            chapter_label="Chapter 0 : Pre-Algebra",
        )
        session.add_all([section, answers])
        session.commit()
        return course.id, section.id
    finally:
        session.close()


def test_get_practice_assessment_reports_not_started_without_side_effect(client):
    course_id, section_id = _course_with_practice_section()

    response = client.get(f"/api/courses/{course_id}/sections/{section_id}/practice-assessment")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_started"
    assert body["run_id"] is None
    assert body["job_id"] is None


def test_start_practice_assessment_starts_lazy_generation(client):
    course_id, section_id = _course_with_practice_section()

    response = client.post(f"/api/courses/{course_id}/sections/{section_id}/practice-assessment")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "generating"
    assert body["run_id"]
    assert body["job_id"]


def test_get_practice_assessment_rejects_non_practice_section(client):
    session = get_session()
    try:
        course = Course(title="Practice API Course")
        session.add(course)
        session.flush()
        section = Section(
            id="content-section",
            course_id=course.id,
            order_index=1,
            title="Lesson",
            body_md="Lesson body",
            content_hash="content-hash",
            kind="content",
            chapter_label="Chapter 0 : Pre-Algebra",
        )
        session.add(section)
        session.commit()
        course_id = course.id
    finally:
        session.close()

    response = client.get(f"/api/courses/{course_id}/sections/content-section/practice-assessment")

    assert response.status_code == 400
    assert response.json()["detail"] == "section is not a practice section"
```

Run:

```bash
cd backend
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_practice_api.py -p no:cacheprovider
```

Expected: FAIL because the router and service do not exist.

- [ ] **Step 2: Add schemas**

In `backend/app/schemas.py`, add a practice section after the quiz schemas:

```python
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
    answered: PracticeAnsweredOut | None = None


class PracticeAssessmentOut(BaseModel):
    status: Literal["ready", "generating", "failed", "not_started"]
    section_id: str
    questions: list[PracticeQuestionOut] = Field(default_factory=list)
    run_id: str | None = None
    job_id: str | None = None
    message: str | None = None


class SubmitPracticeAnswerIn(BaseModel):
    selected_index: int


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
```

- [ ] **Step 3: Add the service skeleton with lazy run creation**

Create `backend/app/services/practice_service.py`:

```python
from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.engine import get_session
from app.db.models import Job, PracticeExtractionRun, PracticeQuestion, Section
from app.services.jobs_service import create_job_in_session

EXTRACTION_VERSION = "v3"
LEARNER_COOKIE = "smv2_learner"


class CourseNotFoundError(ValueError):
    pass


class SectionNotFoundError(ValueError):
    pass


class NotPracticeSectionError(ValueError):
    pass


def _fingerprint_for(section: Section, answer_sections: list[Section]) -> str:
    h = hashlib.sha256()
    h.update(section.id.encode())
    h.update(section.content_hash.encode())
    h.update(EXTRACTION_VERSION.encode())
    for answer in answer_sections:
        h.update(answer.id.encode())
        h.update(answer.content_hash.encode())
    return h.hexdigest()


def _answer_sections(session: Session, section: Section) -> list[Section]:
    return (
        session.query(Section)
        .filter(
            Section.course_id == section.course_id,
            Section.kind == "answers",
            Section.chapter_label == section.chapter_label,
        )
        .order_by(Section.order_index)
        .all()
    )


def get_assessment(course_id: str, section_id: str, learner_key: str) -> tuple[int, dict[str, Any]]:
    session = get_session()
    try:
        section = session.get(Section, section_id)
        if section is None or section.course_id != course_id:
            raise SectionNotFoundError("section not found")
        if section.kind != "practice":
            raise NotPracticeSectionError("section is not a practice section")

        questions = (
            session.query(PracticeQuestion)
            .filter(
                PracticeQuestion.course_id == course_id,
                PracticeQuestion.section_id == section_id,
                PracticeQuestion.status == "ready",
            )
            .order_by(PracticeQuestion.problem_number, PracticeQuestion.created_at)
            .all()
        )
        if questions:
            return 200, {
                "status": "ready",
                "section_id": section_id,
                "questions": _serialize_questions(session, questions, learner_key),
            }

        run = (
            session.query(PracticeExtractionRun)
            .filter(
                PracticeExtractionRun.course_id == course_id,
                PracticeExtractionRun.section_id == section_id,
            )
            .order_by(PracticeExtractionRun.created_at.desc())
            .first()
        )
        if run is None:
            return 200, {
                "status": "not_started",
                "section_id": section_id,
                "message": "Practice questions have not been extracted yet.",
            }
        if run.status == "failed":
            return 200, {
                "status": "failed",
                "section_id": section_id,
                "run_id": run.id,
                "job_id": run.job_id,
                "message": run.error or "Practice extraction failed.",
            }
        elif run.job_id:
            job = session.get(Job, run.job_id)
            if job is not None and job.status == "failed":
                run.status = "failed"
                run.error = job.error or "Practice extraction failed."
                session.commit()
                return 200, {
                    "status": "failed",
                    "section_id": section_id,
                    "run_id": run.id,
                    "job_id": run.job_id,
                    "message": run.error,
                }
        return 202, {
            "status": "generating",
            "section_id": section_id,
            "run_id": run.id,
            "job_id": run.job_id,
            "message": "Practice questions are being extracted from the textbook.",
        }
    finally:
        session.close()


def start_assessment(course_id: str, section_id: str) -> tuple[int, dict[str, Any]]:
    session = get_session()
    try:
        section = session.get(Section, section_id)
        if section is None or section.course_id != course_id:
            raise SectionNotFoundError("section not found")
        if section.kind != "practice":
            raise NotPracticeSectionError("section is not a practice section")
        answers = _answer_sections(session, section)
        fingerprint = _fingerprint_for(section, answers)
        run = (
            session.query(PracticeExtractionRun)
            .filter(
                PracticeExtractionRun.course_id == course_id,
                PracticeExtractionRun.section_id == section_id,
                PracticeExtractionRun.input_fingerprint == fingerprint,
            )
            .first()
        )
        if run is None:
            run = PracticeExtractionRun(
                course_id=course_id,
                section_id=section_id,
                status="queued",
                input_fingerprint=fingerprint,
            )
            session.add(run)
            session.flush()
            job = create_job_in_session(
                session,
                "generate_practice_assessment",
                {"course_id": course_id, "section_id": section_id, "run_id": run.id},
            )
            run.job_id = job.id
            session.commit()
        return 202, {
            "status": "generating",
            "section_id": section_id,
            "run_id": run.id,
            "job_id": run.job_id,
            "message": "Practice questions are being extracted from the textbook.",
        }
    except IntegrityError:
        session.rollback()
        return start_assessment(course_id, section_id)
    finally:
        session.close()
```

Add `_serialize_questions` as a small helper that returns an empty `answered` value for now; Task 4 fills existing answer summaries.

- [ ] **Step 4: Add router and include it**

Create `backend/app/routers/practice.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response

from app.schemas import PracticeAssessmentOut
from app.services import practice_service

router = APIRouter(tags=["practice"])


def _learner_key(request: Request, response: Response) -> str:
    current = request.cookies.get(practice_service.LEARNER_COOKIE)
    if current:
        return current
    created = str(uuid.uuid4())
    response.set_cookie(
        practice_service.LEARNER_COOKIE,
        created,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return created


@router.get(
    "/api/courses/{course_id}/sections/{section_id}/practice-assessment",
    operation_id="get_practice_assessment",
    response_model=PracticeAssessmentOut,
)
def get_practice_assessment(
    course_id: str,
    section_id: str,
    request: Request,
    response: Response,
) -> PracticeAssessmentOut:
    learner_key = _learner_key(request, response)
    try:
        status_code, payload = practice_service.get_assessment(course_id, section_id, learner_key)
    except practice_service.SectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except practice_service.NotPracticeSectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    response.status_code = status_code
    return PracticeAssessmentOut.model_validate(payload)


@router.post(
    "/api/courses/{course_id}/sections/{section_id}/practice-assessment",
    operation_id="start_practice_assessment",
    status_code=202,
    response_model=PracticeAssessmentOut,
)
def start_practice_assessment(
    course_id: str,
    section_id: str,
) -> PracticeAssessmentOut:
    try:
        status_code, payload = practice_service.start_assessment(course_id, section_id)
    except practice_service.SectionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except practice_service.NotPracticeSectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PracticeAssessmentOut.model_validate(payload)
```

Also import `uuid` at the top. In `backend/app/main.py`, import `practice` from `app.routers` and add `app.include_router(practice.router)` near the other learning routes.

- [ ] **Step 5: Register the job type as a temporary no-op**

In `backend/app/jobs/registry.py`, add a handler that marks the run failed until Task 3 supplies extraction:

```python
def _generate_practice_assessment_handler(session: Session, job: Job) -> dict[str, Any]:
    raise ValueError("practice assessment extraction is not wired yet")
```

Add `"generate_practice_assessment": _generate_practice_assessment_handler` to `JOB_HANDLERS`. This is intentionally temporary so the lazy API can enqueue a known job type before extraction exists.

- [ ] **Step 6: Run lazy API tests**

Run:

```bash
cd backend
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_practice_api.py -p no:cacheprovider
```

Expected: PASS for the lazy status tests.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas.py backend/app/services/practice_service.py backend/app/routers/practice.py backend/app/main.py backend/app/jobs/registry.py backend/tests/test_practice_api.py backend/tests/test_practice_service.py
git commit -m "feat: add lazy practice assessment API"
```

## Task 3: Add Textbook-Backed Extraction Job

**Files:**

- Create: `backend/prompts/v3/practice_assessment.md`
- Create: `backend/app/pipeline/practice_extraction.py`
- Modify: `backend/app/jobs/registry.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/test_practice_extraction.py`
- Modify: `backend/tests/test_practice_api.py`

- [ ] **Step 1: Write extraction tests**

Create `backend/tests/test_practice_extraction.py`:

```python
from __future__ import annotations

import json

from app.db.engine import get_session
from app.db.models import Course, Job, PracticeExtractionRun, PracticeQuestion, Section
from app.jobs.worker import run_due_jobs_once
from app.llm.provider import CompletionResult
from app.pipeline.practice_extraction import parse_practice_questions


def test_parse_practice_questions_drops_unmapped_answer():
    payload = json.dumps([
        {
            "problem_number": "1",
            "stem_md": "Simplify $42/12$.",
            "textbook_answer_md": "$7/2$",
            "choices": ["$7/2$", "$2/7$", "$3/4$", "$14/3$"],
            "correct_index": 0,
            "explanation_md": "$42/12 = 7/2$.",
            "concept_slug": "fractions.simplify",
            "concept_label": "Simplifying Fractions",
            "answer_source_ref": "Chapter 0 Answers #1",
            "confidence": 0.98,
        },
        {
            "problem_number": "2",
            "stem_md": "Simplify $10/20$.",
            "textbook_answer_md": "",
            "choices": ["$1/2$", "$2$", "$10$", "$20$"],
            "correct_index": 0,
            "explanation_md": "",
            "concept_slug": "fractions.simplify",
            "concept_label": "Simplifying Fractions",
            "answer_source_ref": "",
            "confidence": 0.3,
        },
    ])

    questions = parse_practice_questions(payload)

    assert len(questions) == 1
    assert questions[0]["problem_number"] == "1"
    assert questions[0]["choices"][questions[0]["correct_index"]] == "$7/2$"


def test_practice_extraction_job_persists_ready_questions(client, stub_provider):
    stub_provider.responses = [
        CompletionResult(
            text=json.dumps([
                {
                    "problem_number": "1",
                    "stem_md": "Simplify $42/12$.",
                    "textbook_answer_md": "$7/2$",
                    "choices": ["$7/2$", "$2/7$", "$3/4$", "$14/3$"],
                    "correct_index": 0,
                    "explanation_md": "$42/12 = 7/2$.",
                    "concept_slug": "fractions.simplify",
                    "concept_label": "Simplifying Fractions",
                    "answer_source_ref": "Chapter 0 Answers #1",
                    "confidence": 0.98,
                }
            ]),
            input_tokens=100,
            output_tokens=200,
            model="stub-model",
        )
    ]
    session = get_session()
    try:
        course = Course(title="Extraction Course")
        session.add(course)
        session.flush()
        practice = Section(
            id="practice-extraction-section",
            course_id=course.id,
            order_index=1,
            title="0.2 Practice - Fractions",
            body_md="1. Simplify 42/12",
            content_hash="practice-extraction-hash",
            kind="practice",
            chapter_label="Chapter 0 : Pre-Algebra",
        )
        answers = Section(
            id="answers-extraction-section",
            course_id=course.id,
            order_index=2,
            title="Chapter 0 Answers",
            body_md="1. 7/2",
            content_hash="answers-extraction-hash",
            kind="answers",
            chapter_label="Chapter 0 : Pre-Algebra",
        )
        run = PracticeExtractionRun(
            course_id=course.id,
            section_id=practice.id,
            status="queued",
            input_fingerprint="run-fingerprint",
        )
        session.add_all([practice, answers, run])
        session.flush()
        job = Job(
            type="generate_practice_assessment",
            status="queued",
            payload={"course_id": course.id, "section_id": practice.id, "run_id": run.id},
        )
        session.add(job)
        run.job_id = job.id
        session.commit()
        run_id = run.id
        course_id = course.id
    finally:
        session.close()

    assert run_due_jobs_once() is True

    session = get_session()
    try:
        stored_run = session.get(PracticeExtractionRun, run_id)
        assert stored_run.status == "ready"
        questions = session.query(PracticeQuestion).filter_by(course_id=course_id).all()
        assert len(questions) == 1
        assert questions[0].correct_index == 0
        assert questions[0].status == "ready"
    finally:
        session.close()
```

Run:

```bash
cd backend
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_practice_extraction.py -p no:cacheprovider
```

Expected: FAIL because extraction code does not exist.

- [ ] **Step 2: Add the prompt file**

Create `backend/prompts/v3/practice_assessment.md`:

```markdown
You extract textbook practice problems into gradeable multiple-choice questions.

Rules:
- Return JSON only.
- The correct answer must come from the provided answer key text.
- If a problem cannot be matched to an answer-key entry, omit it.
- Use Markdown with LaTeX math for stems, choices, and explanations.
- Generate exactly four choices.
- Include the textbook answer as one choice and set correct_index to that choice.
- Use a concise concept_slug such as fractions.simplify or inequalities.solve-linear.
- Use a user-facing concept_label.
- Set confidence below 0.7 when answer mapping is uncertain.

Return an array of objects with:
- problem_number
- stem_md
- textbook_answer_md
- choices
- correct_index
- explanation_md
- concept_slug
- concept_label
- answer_source_ref
- confidence
```

- [ ] **Step 3: Implement parser and job**

Create `backend/app/pipeline/practice_extraction.py` with:

```python
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Concept, Job, PracticeExtractionRun, PracticeQuestion, Section
from app.llm.ledger import ensure_spend_cap, record_llm_call
from app.llm.prompts import load_prompt
from app.llm.provider import get_provider
from app.pipeline._common import report_progress_in_session, strip_leading_fence

logger = logging.getLogger(__name__)

_MAX_TOKENS = 4096
_MIN_CONFIDENCE = 0.7


def parse_practice_questions(text: str) -> list[dict[str, Any]]:
    data = json.loads(strip_leading_fence(text))
    if not isinstance(data, list):
        raise ValueError("expected a JSON array of practice questions")
    parsed: list[dict[str, Any]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            logger.warning("dropping malformed practice item %d: not an object", i)
            continue
        problem_number = item.get("problem_number")
        stem_md = item.get("stem_md")
        textbook_answer_md = item.get("textbook_answer_md")
        choices = item.get("choices")
        correct_index = item.get("correct_index")
        explanation_md = item.get("explanation_md")
        concept_slug = item.get("concept_slug")
        concept_label = item.get("concept_label")
        answer_source_ref = item.get("answer_source_ref")
        confidence = item.get("confidence")
        if not isinstance(problem_number, str) or not problem_number.strip():
            continue
        if not isinstance(stem_md, str) or not stem_md.strip():
            continue
        if not isinstance(textbook_answer_md, str) or not textbook_answer_md.strip():
            continue
        if not isinstance(choices, list) or len(choices) != 4 or not all(isinstance(c, str) and c.strip() for c in choices):
            continue
        if not isinstance(correct_index, int) or isinstance(correct_index, bool) or not 0 <= correct_index < 4:
            continue
        if choices[correct_index].strip() != textbook_answer_md.strip():
            continue
        if not isinstance(explanation_md, str) or not explanation_md.strip():
            continue
        if not isinstance(concept_slug, str) or not concept_slug.strip():
            continue
        if not isinstance(concept_label, str) or not concept_label.strip():
            continue
        if not isinstance(answer_source_ref, str) or not answer_source_ref.strip():
            continue
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or confidence < _MIN_CONFIDENCE:
            continue
        parsed.append({
            "problem_number": problem_number.strip(),
            "stem_md": stem_md.strip(),
            "choices": [c.strip() for c in choices],
            "correct_index": correct_index,
            "explanation_md": explanation_md.strip(),
            "concept_slug": concept_slug.strip(),
            "concept_label": concept_label.strip(),
            "answer_source_ref": answer_source_ref.strip(),
            "confidence": float(confidence),
        })
    return parsed
```

Add `run_practice_extraction(session, job, course_id, section_id, run_id)` that:

- Loads the `PracticeExtractionRun`, practice `Section`, and same-chapter answer sections.
- Sets `run.status = "running"`.
- Calls `load_prompt("practice_assessment")`.
- Builds a user message with `<practice_section>` and `<answer_key_sections>`.
- Calls `ensure_spend_cap(course_id)` immediately before `provider.complete`.
- Parses with `parse_practice_questions`.
- Upserts `Concept` by `(course_id, slug)`.
- Inserts `PracticeQuestion` rows with a `source_fingerprint` hash of `section.content_hash`, `problem_number`, `answer_source_ref`, and prompt version.
- Sets `run.status = "ready"` and `run.question_count`.
- Raises `ValueError("practice assessment extraction produced zero usable questions")` when no usable questions remain.

- [ ] **Step 4: Wire job registry and provider patching**

In `backend/app/jobs/registry.py`, import `run_practice_extraction` and replace the temporary handler:

```python
def _generate_practice_assessment_handler(session: Session, job: Job) -> dict[str, Any]:
    payload = job.payload or {}
    course_id = payload.get("course_id")
    section_id = payload.get("section_id")
    run_id = payload.get("run_id")
    if not course_id:
        raise ValueError("generate_practice_assessment job payload missing course_id")
    if not section_id:
        raise ValueError("generate_practice_assessment job payload missing section_id")
    if not run_id:
        raise ValueError("generate_practice_assessment job payload missing run_id")
    extra = run_practice_extraction(session, job, course_id, section_id, run_id)
    return {"course_id": course_id, "section_id": section_id, "run_id": run_id, **extra}
```

In `backend/tests/conftest.py`, add `"app.pipeline.practice_extraction.get_provider"` to `_GET_PROVIDER_PATCH_TARGETS`.

- [ ] **Step 5: Add failed run polling behavior**

Do not try to mark `PracticeExtractionRun` as failed inside the job handler immediately before re-raising. The worker rolls back the handler session when an exception escapes, so that update would be lost. Instead, keep the raised exception so the linked `Job` becomes `failed`, and make `practice_service.get_assessment` detect a linked failed job on the next poll:

```python
job = session.get(Job, run.job_id) if run.job_id else None
if job is not None and job.status == "failed":
    run.status = "failed"
    run.error = job.error or "Practice extraction failed."
    session.commit()
    return 200, {
        "status": "failed",
        "section_id": section_id,
        "run_id": run.id,
        "job_id": run.job_id,
        "message": run.error,
    }
```

Add an API test that creates a `PracticeExtractionRun` linked to a failed `Job`, calls the GET endpoint, and asserts `status == "failed"` plus a safe message.

- [ ] **Step 6: Run extraction tests**

Run:

```bash
cd backend
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_practice_extraction.py tests/test_practice_api.py -p no:cacheprovider
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/prompts/v3/practice_assessment.md backend/app/pipeline/practice_extraction.py backend/app/jobs/registry.py backend/tests/conftest.py backend/tests/test_practice_extraction.py backend/tests/test_practice_api.py
git commit -m "feat: extract textbook-backed practice questions"
```

## Task 4: Add Immediate Answer Grading and Concept Mastery

**Files:**

- Modify: `backend/app/services/practice_service.py`
- Modify: `backend/app/routers/practice.py`
- Modify: `backend/app/schemas.py`
- Create/modify: `backend/tests/test_practice_service.py`
- Modify: `backend/tests/test_practice_api.py`

- [ ] **Step 1: Write grading tests**

Create `backend/tests/test_practice_service.py` with test fixtures that insert one ready `PracticeQuestion`. Include these tests:

```python
def test_submit_wrong_answer_records_negative_mastery(client):
    question_id, course_id = seed_ready_practice_question(correct_index=0)

    result = practice_service.submit_answer(course_id, question_id, "learner-1", selected_index=1)

    assert result["correct"] is False
    assert result["correct_index"] == 0
    assert result["points_delta"] == -1
    assert result["mastery_points"] == -1
    assert result["already_answered"] is False


def test_duplicate_submit_returns_original_result_without_second_delta(client):
    question_id, course_id = seed_ready_practice_question(correct_index=0)

    first = practice_service.submit_answer(course_id, question_id, "learner-1", selected_index=1)
    second = practice_service.submit_answer(course_id, question_id, "learner-1", selected_index=0)

    assert first["points_delta"] == -1
    assert second["selected_index"] == 1
    assert second["correct"] is False
    assert second["already_answered"] is True
    assert second["mastery_points"] == -1
```

Also add API tests:

```python
def test_answer_endpoint_sets_learner_cookie_and_reveals_answer(client):
    question_id, course_id = seed_ready_practice_question(correct_index=0)

    response = client.post(
        f"/api/courses/{course_id}/practice-questions/{question_id}/answer",
        json={"selected_index": 1},
    )

    assert response.status_code == 200
    assert "smv2_learner=" in response.headers["set-cookie"]
    body = response.json()
    assert body["correct"] is False
    assert body["correct_index"] == 0
    assert body["points_delta"] == -1
```

Run:

```bash
cd backend
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_practice_service.py tests/test_practice_api.py -p no:cacheprovider
```

Expected: FAIL because grading is not implemented.

- [ ] **Step 2: Implement `submit_answer`**

In `backend/app/services/practice_service.py`, implement:

```python
class PracticeQuestionNotFoundError(ValueError):
    pass


class InvalidChoiceError(ValueError):
    pass


def submit_answer(course_id: str, question_id: str, learner_key: str, selected_index: int) -> dict[str, Any]:
    session = get_session()
    try:
        question = (
            session.query(PracticeQuestion)
            .filter(PracticeQuestion.id == question_id, PracticeQuestion.course_id == course_id)
            .first()
        )
        if question is None:
            raise PracticeQuestionNotFoundError("practice question not found")
        if not 0 <= selected_index < len(question.choices):
            raise InvalidChoiceError("selected_index is out of range")

        existing = (
            session.query(PracticeAnswer)
            .filter(PracticeAnswer.question_id == question_id, PracticeAnswer.learner_key == learner_key)
            .first()
        )
        if existing is not None:
            mastery = _get_mastery(session, course_id, question.concept_id, learner_key)
            return _answer_payload(session, question, existing, mastery.points, already_answered=True)

        correct = selected_index == question.correct_index
        delta = 1 if correct else -1
        answer = PracticeAnswer(
            course_id=course_id,
            question_id=question.id,
            learner_key=learner_key,
            selected_index=selected_index,
            correct=correct,
            points_delta=delta,
        )
        session.add(answer)
        session.flush()
        mastery = _get_mastery(session, course_id, question.concept_id, learner_key)
        mastery.points += delta
        if correct:
            mastery.correct_count += 1
        else:
            mastery.wrong_count += 1
        event = ConceptMasteryEvent(
            course_id=course_id,
            concept_id=question.concept_id,
            question_id=question.id,
            practice_answer_id=answer.id,
            learner_key=learner_key,
            delta=delta,
        )
        session.add(event)
        session.commit()
        return _answer_payload(session, question, answer, mastery.points, already_answered=False)
    except IntegrityError:
        session.rollback()
        return submit_answer(course_id, question_id, learner_key, selected_index)
    finally:
        session.close()
```

Add `_get_mastery` to create a zeroed `ConceptMastery` row when missing. Add `_answer_payload` to include concept id/slug/label, `correct_index`, explanation, delta, and mastery points.

- [ ] **Step 3: Add answered summaries to ready assessment response**

Update `_serialize_questions` so it loads `PracticeAnswer` rows for the current `learner_key` and includes the original answered result for any answered question. The `answered` summary may include `correct_index` because the learner already answered that specific question.

- [ ] **Step 4: Add answer endpoint**

In `backend/app/routers/practice.py`, add:

```python
@router.post(
    "/api/courses/{course_id}/practice-questions/{question_id}/answer",
    operation_id="submit_practice_answer",
    response_model=SubmitPracticeAnswerOut,
)
def submit_practice_answer(
    course_id: str,
    question_id: str,
    body: SubmitPracticeAnswerIn,
    request: Request,
    response: Response,
) -> SubmitPracticeAnswerOut:
    learner_key = _learner_key(request, response)
    try:
        result = practice_service.submit_answer(course_id, question_id, learner_key, body.selected_index)
    except practice_service.PracticeQuestionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except practice_service.InvalidChoiceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SubmitPracticeAnswerOut.model_validate(result)
```

Import `SubmitPracticeAnswerIn` and `SubmitPracticeAnswerOut`.

- [ ] **Step 5: Run grading tests**

Run:

```bash
cd backend
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q tests/test_practice_service.py tests/test_practice_api.py -p no:cacheprovider
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/practice_service.py backend/app/routers/practice.py backend/app/schemas.py backend/tests/test_practice_service.py backend/tests/test_practice_api.py
git commit -m "feat: grade inline practice answers"
```

## Task 5: Regenerate OpenAPI and Add Frontend API Helpers

**Files:**

- Modify: `openapi.json`
- Modify: `frontend/lib/api/schema.d.ts`
- Modify: `frontend/lib/api/client.ts`

- [ ] **Step 1: Export OpenAPI**

Run:

```bash
cd backend
uv run python -m app.export_openapi ../openapi.json
```

Expected: command prints `wrote OpenAPI schema to ../openapi.json`.

- [ ] **Step 2: Regenerate TypeScript schema**

Run:

```bash
cd frontend
npm run gen:api
```

Expected: command exits 0 and updates `frontend/lib/api/schema.d.ts`.

- [ ] **Step 3: Add frontend helper exports**

In `frontend/lib/api/client.ts`, export the new types near the quiz exports:

```ts
export type PracticeAssessmentOut = components["schemas"]["PracticeAssessmentOut"];
export type PracticeQuestionOut = components["schemas"]["PracticeQuestionOut"];
export type PracticeConceptOut = components["schemas"]["PracticeConceptOut"];
export type PracticeAnsweredOut = components["schemas"]["PracticeAnsweredOut"];
export type SubmitPracticeAnswerOut = components["schemas"]["SubmitPracticeAnswerOut"];
```

Add helper functions near `getSection`:

```ts
export function getPracticeAssessment(courseId: string, sectionId: string) {
  return request(
    client.GET("/api/courses/{course_id}/sections/{section_id}/practice-assessment", {
      params: { path: { course_id: courseId, section_id: sectionId } },
    }),
  );
}

export function startPracticeAssessment(courseId: string, sectionId: string) {
  return request(
    client.POST("/api/courses/{course_id}/sections/{section_id}/practice-assessment", {
      params: { path: { course_id: courseId, section_id: sectionId } },
    }),
  );
}

export function submitPracticeAnswer(courseId: string, questionId: string, selectedIndex: number) {
  return request(
    client.POST("/api/courses/{course_id}/practice-questions/{question_id}/answer", {
      params: { path: { course_id: courseId, question_id: questionId } },
      body: { selected_index: selectedIndex },
    }),
  );
}
```

- [ ] **Step 4: Typecheck frontend API**

Run:

```bash
cd frontend
npm run typecheck
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add openapi.json frontend/lib/api/schema.d.ts frontend/lib/api/client.ts
git commit -m "feat: expose practice assessment API client"
```

## Task 6: Build Inline Practice Assessment Component

**Files:**

- Create: `frontend/components/chapter/InlinePracticeAssessment.tsx`
- Create: `frontend/__tests__/inline-practice-assessment.test.tsx`

- [ ] **Step 1: Write focused component tests**

Create `frontend/__tests__/inline-practice-assessment.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import InlinePracticeAssessment from "@/components/chapter/InlinePracticeAssessment";
import { getPracticeAssessment, startPracticeAssessment, submitPracticeAnswer } from "@/lib/api/client";

import { ok } from "./support/api-result";

vi.mock("@/lib/api/client", () => ({
  getPracticeAssessment: vi.fn(),
  startPracticeAssessment: vi.fn(),
  submitPracticeAnswer: vi.fn(),
}));

const mockedGetPracticeAssessment = vi.mocked(getPracticeAssessment);
const mockedStartPracticeAssessment = vi.mocked(startPracticeAssessment);
const mockedSubmitPracticeAnswer = vi.mocked(submitPracticeAnswer);

describe("InlinePracticeAssessment", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders ready questions and reveals the textbook answer after a wrong choice", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(
      ok({
        status: "ready",
        section_id: "section-1",
        questions: [
          {
            id: "question-1",
            problem_number: "1",
            source_ref: "0.2 Practice - Fractions #1",
            stem_md: "Simplify $42/12$.",
            choices: ["$7/2$", "$2/7$", "$3/4$", "$14/3$"],
            concept: { id: "concept-1", slug: "fractions.simplify", label: "Simplifying Fractions" },
            answered: null,
          },
        ],
        run_id: null,
        job_id: null,
        message: null,
      }),
    );
    mockedSubmitPracticeAnswer.mockResolvedValue(
      ok({
        question_id: "question-1",
        selected_index: 1,
        correct: false,
        correct_index: 0,
        explanation_md: "$42/12 = 7/2$.",
        concept: { id: "concept-1", slug: "fractions.simplify", label: "Simplifying Fractions" },
        points_delta: -1,
        mastery_points: -1,
        already_answered: false,
      }),
    );

    const user = userEvent.setup();
    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    expect(await screen.findByText(/simplify/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /\$2\/7\$/i }));

    expect(await screen.findByText(/incorrect/i)).toBeInTheDocument();
    expect(screen.getByText(/concept points: -1/i)).toBeInTheDocument();
    expect(screen.getByText(/\$42\/12 = 7\/2\$/i)).toBeInTheDocument();
  });

  it("shows a generating state while extraction is pending", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(
      ok({
        status: "generating",
        section_id: "section-1",
        questions: [],
        run_id: "run-1",
        job_id: "job-1",
        message: "Practice questions are being extracted from the textbook.",
      }, 202),
    );

    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    expect(await screen.findByRole("status")).toHaveTextContent(/extracted from the textbook/i);
  });

  it("starts extraction with POST when the read-only status is not_started", async () => {
    mockedGetPracticeAssessment
      .mockResolvedValueOnce(
        ok({
          status: "not_started",
          section_id: "section-1",
          questions: [],
          run_id: null,
          job_id: null,
          message: "Practice questions have not been extracted yet.",
        }),
      )
      .mockResolvedValueOnce(
        ok({
          status: "generating",
          section_id: "section-1",
          questions: [],
          run_id: "run-1",
          job_id: "job-1",
          message: "Practice questions are being extracted from the textbook.",
        }, 202),
      );
    mockedStartPracticeAssessment.mockResolvedValue(
      ok({
        status: "generating",
        section_id: "section-1",
        questions: [],
        run_id: "run-1",
        job_id: "job-1",
        message: "Practice questions are being extracted from the textbook.",
      }, 202),
    );

    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    await waitFor(() => expect(mockedStartPracticeAssessment).toHaveBeenCalledWith("course-1", "section-1"));
  });
});
```

Run:

```bash
cd frontend
npm test -- inline-practice-assessment.test.tsx
```

Expected: FAIL because the component does not exist.

- [ ] **Step 2: Implement component**

Create `frontend/components/chapter/InlinePracticeAssessment.tsx`:

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Markdown from "@/components/Markdown";
import Button from "@/components/ui/Button";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  getPracticeAssessment,
  startPracticeAssessment,
  submitPracticeAnswer,
  type PracticeAssessmentOut,
  type SubmitPracticeAnswerOut,
} from "@/lib/api/client";

interface InlinePracticeAssessmentProps {
  courseId: string;
  sectionId: string;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "ready"; assessment: PracticeAssessmentOut };

export default function InlinePracticeAssessment({ courseId, sectionId }: InlinePracticeAssessmentProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [answers, setAnswers] = useState<Record<string, SubmitPracticeAnswerOut>>({});
  const [submittingId, setSubmittingId] = useState<string | null>(null);

  const applyAssessment = useCallback((assessment: PracticeAssessmentOut) => {
    setState({ kind: "ready", assessment });
    const restored: Record<string, SubmitPracticeAnswerOut> = {};
    for (const question of assessment.questions) {
      if (question.answered) {
        restored[question.id] = {
          question_id: question.id,
          selected_index: question.answered.selected_index,
          correct: question.answered.correct,
          correct_index: question.answered.correct_index,
          explanation_md: question.answered.explanation_md,
          concept: question.concept,
          points_delta: question.answered.points_delta,
          mastery_points: question.answered.mastery_points,
          already_answered: true,
        };
      }
    }
    setAnswers(restored);
  }, []);

  const load = useCallback(async () => {
    const { data, status } = await getPracticeAssessment(courseId, sectionId);
    if (!data) {
      setState({ kind: "error", error: describeError(status, "Loading practice questions") });
      return;
    }
    applyAssessment(data);
  }, [applyAssessment, courseId, sectionId]);

  useEffect(() => {
    let active = true;
    getPracticeAssessment(courseId, sectionId).then(({ data, status }) => {
      if (!active) return;
      if (!data) {
        setState({ kind: "error", error: describeError(status, "Loading practice questions") });
      } else {
        applyAssessment(data);
      }
    });
    return () => {
      active = false;
    };
  }, [applyAssessment, courseId, sectionId]);

  useEffect(() => {
    if (state.kind !== "ready" || state.assessment.status !== "not_started") return;
    let active = true;
    startPracticeAssessment(courseId, sectionId).then(({ data }) => {
      if (active && data) applyAssessment(data);
    });
    return () => {
      active = false;
    };
  }, [applyAssessment, courseId, sectionId, state]);

  useEffect(() => {
    if (state.kind !== "ready" || state.assessment.status !== "generating") return;
    const timer = window.setTimeout(() => void load(), 1500);
    return () => window.clearTimeout(timer);
  }, [load, state]);

  async function answer(questionId: string, selectedIndex: number) {
    setSubmittingId(questionId);
    const { data } = await submitPracticeAnswer(courseId, questionId, selectedIndex);
    setSubmittingId(null);
    if (data) setAnswers((current) => ({ ...current, [questionId]: data }));
  }

  if (state.kind === "loading") {
    return <p role="status" className="text-sm text-muted-foreground">Loading practice questions...</p>;
  }
  if (state.kind === "error") {
    return <ErrorBanner status={state.error.status} message={state.error.message} onRetry={() => void load()} />;
  }
  if (state.assessment.status === "generating") {
    return <p role="status" className="text-sm text-muted-foreground">{state.assessment.message ?? "Extracting practice questions..."}</p>;
  }
  if (state.assessment.status === "not_started") {
    return <p role="status" className="text-sm text-muted-foreground">Preparing practice questions...</p>;
  }
  if (state.assessment.status === "failed") {
    return <ErrorBanner message={state.assessment.message ?? "Practice extraction failed."} onRetry={() => void load()} />;
  }
  return (
    <div className="flex flex-col gap-4">
      {state.assessment.questions.map((question) => {
        const result = answers[question.id];
        return (
          <article key={question.id} className="rounded-lg border border-border p-4">
            <div className="mb-2 flex items-center justify-between gap-3 text-xs text-muted-foreground">
              <span>{question.source_ref}</span>
              <span>{question.concept.label}</span>
            </div>
            <div className="mb-3 text-sm">
              <Markdown>{question.stem_md}</Markdown>
            </div>
            <div className="grid gap-2">
              {question.choices.map((choice, index) => (
                <Button
                  key={`${question.id}-${index}`}
                  variant={result?.selected_index === index ? "primary" : "secondary"}
                  disabled={Boolean(result) || submittingId === question.id}
                  onClick={() => void answer(question.id, index)}
                  className="justify-start text-left"
                >
                  <Markdown>{choice}</Markdown>
                </Button>
              ))}
            </div>
            {result && (
              <div className="mt-3 rounded-md bg-muted-foreground/5 p-3 text-sm">
                <p className={result.correct ? "font-medium text-green-700 dark:text-green-400" : "font-medium text-red-700 dark:text-red-400"}>
                  {result.correct ? "Correct" : "Incorrect"}
                </p>
                <p className="mt-1 text-muted-foreground">Concept points: {result.mastery_points}</p>
                <div className="mt-2">
                  <Markdown>{result.explanation_md}</Markdown>
                </div>
              </div>
            )}
          </article>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 3: Run focused frontend tests**

Run:

```bash
cd frontend
npm test -- inline-practice-assessment.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/chapter/InlinePracticeAssessment.tsx frontend/__tests__/inline-practice-assessment.test.tsx
git commit -m "feat: add inline practice assessment UI"
```

## Task 7: Integrate Inline Assessment Into Chapter Test Page

**Files:**

- Modify: `frontend/components/chapter/ChapterTestClient.tsx`
- Modify: `frontend/__tests__/chapter-test-client.test.tsx`

- [ ] **Step 1: Write integration tests**

Update the `@/lib/api/client` mock in `frontend/__tests__/chapter-test-client.test.tsx` to include `getPracticeAssessment` and `submitPracticeAnswer`, or mock `InlinePracticeAssessment` directly:

```tsx
vi.mock("@/components/chapter/InlinePracticeAssessment", () => ({
  default: ({ sectionId }: { courseId: string; sectionId: string }) => (
    <div data-testid="inline-practice-assessment" data-section-id={sectionId}>
      Inline practice assessment
    </div>
  ),
}));
```

Replace the existing expectation that raw practice body text is the primary display:

```tsx
it("renders inline practice assessments for detected practice sections", async () => {
  mockedListChapters.mockResolvedValue(ok([makeChapter()]));
  mockedGetSection.mockImplementation(mockGetSectionById);
  mockedListTests.mockResolvedValue(ok([]));

  render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

  const assessment = await screen.findByTestId("inline-practice-assessment");
  expect(assessment).toHaveAttribute("data-section-id", "c1-practice");
});
```

Add a test that the answer key is not exposed as a normal disclosure:

```tsx
it("does not expose the printed answer key before inline questions are answered", async () => {
  mockedListChapters.mockResolvedValue(ok([makeChapter()]));
  mockedGetSection.mockImplementation(mockGetSectionById);
  mockedListTests.mockResolvedValue(ok([]));

  render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

  await screen.findByTestId("inline-practice-assessment");
  expect(screen.queryByText("Answer key")).not.toBeInTheDocument();
  expect(screen.queryByText("Answer: 4")).not.toBeInTheDocument();
});
```

Run:

```bash
cd frontend
npm test -- chapter-test-client.test.tsx
```

Expected: FAIL until the page integrates the new component and removes the answer-key disclosure.

- [ ] **Step 2: Integrate component**

In `frontend/components/chapter/ChapterTestClient.tsx`:

- Import `InlinePracticeAssessment`.
- Keep `PracticeMaterial` only for source fallback/details.
- Replace the `Practice material` panel body with one `InlinePracticeAssessment` per practice section.
- Move original page rendering into a collapsed `View textbook source` detail under each assessment.
- Remove the chapter-level `Answer key` disclosure entirely.

The mapped practice section body should be shaped like:

```tsx
{practiceSections.map((section) => (
  <section key={section.id} className="flex flex-col gap-3">
    <InlinePracticeAssessment courseId={courseId} sectionId={section.id} />
    <details className="rounded-md border border-border p-3">
      <summary className="cursor-pointer text-sm font-medium">View textbook source</summary>
      <div className="mt-3">
        <PracticeMaterial courseId={courseId} section={section} />
      </div>
    </details>
  </section>
))}
```

Do not render `answerSections` in this page. The backend extraction job may use answer sections, but the learner page should reveal answers only after an answer submission.

- [ ] **Step 3: Run chapter page tests**

Run:

```bash
cd frontend
npm test -- chapter-test-client.test.tsx inline-practice-assessment.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/chapter/ChapterTestClient.tsx frontend/__tests__/chapter-test-client.test.tsx
git commit -m "feat: show inline practice on chapter test page"
```

## Task 8: End-to-End Verification and Cleanup

**Files:**

- Read/verify: all changed files
- Modify only when test failures reveal a concrete defect

- [ ] **Step 1: Run targeted backend tests**

Run:

```bash
cd backend
PYTHONDONTWRITEBYTECODE=1 uv run pytest -q \
  tests/test_practice_models.py \
  tests/test_practice_service.py \
  tests/test_practice_extraction.py \
  tests/test_practice_api.py \
  tests/test_course_delete_cascade.py \
  tests/test_architecture.py \
  -p no:cacheprovider
```

Expected: PASS.

- [ ] **Step 2: Run targeted frontend tests**

Run:

```bash
cd frontend
npm test -- inline-practice-assessment.test.tsx chapter-test-client.test.tsx markdown.test.tsx
```

Expected: PASS.

- [ ] **Step 3: Regenerate committed API artifacts**

Run:

```bash
cd backend
uv run python -m app.export_openapi ../openapi.json
cd ../frontend
npm run gen:api
```

Expected: both commands exit 0 and `git diff -- openapi.json frontend/lib/api/schema.d.ts` shows only schema changes for practice assessment endpoints and models.

- [ ] **Step 4: Run typecheck and lint**

Run:

```bash
cd frontend
npm run typecheck
npm run lint
```

Expected: both PASS.

- [ ] **Step 5: Run full build gate**

Run from repo root:

```bash
./build.sh
```

Expected: ends with `BUILD OK`.

- [ ] **Step 6: Manual smoke with dev server**

Run from repo root:

```bash
./dev.sh
```

Open:

```text
http://localhost:3000/course/e3a9bdb2-aa11-4ec4-add0-d5e99438dabd/chapter/Chapter%200%20%3A%20Pre-Algebra/test
```

Expected:

- The practice section shows inline questions or a generating status.
- The printed answer key is not visible before answering.
- Selecting a wrong answer immediately reveals the correct answer/explanation.
- The displayed concept points decrease by 1.
- Refreshing the page keeps the answered state locked for that learner cookie.

- [ ] **Step 7: Final commit**

```bash
git status --short
git add \
  backend/app/db/models.py \
  backend/app/db/registry.py \
  backend/app/db/migrations/versions/0009_inline_practice_assessments.py \
  backend/app/pipeline/ingest.py \
  backend/app/pipeline/practice_extraction.py \
  backend/app/jobs/registry.py \
  backend/app/services/practice_service.py \
  backend/app/routers/practice.py \
  backend/app/main.py \
  backend/app/schemas.py \
  backend/prompts/v3/practice_assessment.md \
  backend/tests/conftest.py \
  backend/tests/test_practice_models.py \
  backend/tests/test_practice_reingest.py \
  backend/tests/test_practice_service.py \
  backend/tests/test_practice_extraction.py \
  backend/tests/test_practice_api.py \
  backend/tests/test_course_delete_cascade.py \
  openapi.json \
  frontend/lib/api/schema.d.ts \
  frontend/lib/api/client.ts \
  frontend/components/chapter/InlinePracticeAssessment.tsx \
  frontend/components/chapter/ChapterTestClient.tsx \
  frontend/__tests__/inline-practice-assessment.test.tsx \
  frontend/__tests__/chapter-test-client.test.tsx
git commit -m "feat: add textbook-backed inline practice assessments"
```

Only commit files changed by this implementation branch. Leave unrelated pre-existing worktree changes unstaged.

## Self-Review Checklist

- Spec coverage: dedicated models, lazy global cache, textbook answer source, immediate answer reveal, per-question concept mastery, server grading, safe Markdown rendering, no answer exposure before answering.
- Security coverage: no raw HTML rendering beyond existing sanitized Markdown, no pre-answer `correct_index`, server-side validation of course/question, `HttpOnly` learner cookie, backend-only scoring.
- Repo invariant coverage: thin router, no direct DB imports in routers, prompt stored in `backend/prompts/v3`, new FK models registered in `backend/app/db/registry.py`, OpenAPI artifacts regenerated.
- Verification coverage: targeted backend tests, targeted frontend tests, typecheck, lint, full build, manual smoke.
