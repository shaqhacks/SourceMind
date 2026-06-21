from __future__ import annotations

import logging
import os
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from SourceMind.backend.services.course_engine import CourseEngine, CourseGenerationError, build_course_summary
from SourceMind.backend.services.course_models import (
    Chapter,
    ChatTurn,
    CourseDocument,
    CourseGenerationProgress,
    CourseStatus,
    GenerationStatus,
    SectionLesson,
)
from SourceMind.backend.services.course_store import CourseStore


router = APIRouter(prefix="/courses", tags=["courses"])
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = int(os.getenv("SOURCEMIND_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))
MAX_UPLOAD_FILES = int(os.getenv("SOURCEMIND_MAX_UPLOAD_FILES", "20"))
MAX_TOTAL_UPLOAD_BYTES = int(os.getenv("SOURCEMIND_MAX_TOTAL_UPLOAD_BYTES", str(250 * 1024 * 1024)))
UPLOAD_CHUNK_SIZE = 1024 * 1024
GENERATION_MAX_ATTEMPTS = int(os.getenv("SOURCEMIND_GENERATION_MAX_ATTEMPTS", "5"))
GENERATION_RETRY_BASE_SECONDS = float(os.getenv("SOURCEMIND_GENERATION_RETRY_BASE_SECONDS", "5"))
GENERATION_RETRY_MAX_SECONDS = float(os.getenv("SOURCEMIND_GENERATION_RETRY_MAX_SECONDS", "300"))

course_store = CourseStore()
course_engine = CourseEngine(
    model=os.getenv("OLLAMA_MODEL", "llama3.1"),
    allow_deterministic_fallback=os.getenv("SOURCEMIND_ALLOW_DETERMINISTIC_GENERATION") == "1",
)
_generation_lock = threading.Lock()
_generation_jobs: dict[str, threading.Timer] = {}
_generation_running: set[str] = set()


class CourseUploadResponse(BaseModel):
    course_id: str
    title: str
    status: str
    chapters_count: int
    sections_count: int


class CourseListResponse(BaseModel):
    courses: list[dict[str, Any]]


class ReviewDueItem(BaseModel):
    course_id: str
    course_title: str
    competency_id: str
    competency_title: str
    section_id: str
    section_number: str
    section_title: str
    mastery_percent: float
    last_score: float | None
    next_review_at: str | None
    due: bool
    reason: str


class DueReviewsResponse(BaseModel):
    items: list[ReviewDueItem]
    due_count: int
    upcoming_count: int


class OutlineUpdateRequest(BaseModel):
    chapters: list[Chapter]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)


class ChatResponse(BaseModel):
    answer: str
    support_status: str
    source_refs: list[str]
    created_at: str


class CheckGradeRequest(BaseModel):
    answer: str = ""
    confidence: int = Field(default=4, ge=1, le=6)


class CheckGradeResponse(BaseModel):
    score: float
    passed: bool
    feedback: str


class QuizSubmitRequest(BaseModel):
    answers: dict[str, str] = Field(default_factory=dict)
    confidence: int = Field(default=4, ge=1, le=6)


@router.post("/uploads", response_model=CourseUploadResponse)
async def upload_course_pdfs(
    files: list[UploadFile] = File(...),
    title: str | None = Form(default=None),
) -> CourseUploadResponse:
    if not files:
        raise HTTPException(status_code=422, detail="Choose at least one PDF.")
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=413, detail=f"Upload at most {MAX_UPLOAD_FILES} PDFs at a time.")
    safe_filenames = [_validated_pdf_filename(file) for file in files]
    display_title = title or _default_title(safe_filenames)
    course_id = course_store.unique_id(display_title)

    with tempfile.TemporaryDirectory(prefix="sourcemind-course-") as tmpdir:
        pdf_paths: list[Path] = []
        total_upload_bytes = 0
        for file, safe_filename in zip(files, safe_filenames, strict=True):
            path = _unique_temp_path(Path(tmpdir), safe_filename)
            total_upload_bytes += await _write_upload_file(file, path)
            if total_upload_bytes > MAX_TOTAL_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Uploaded PDFs are too large together. Maximum total size is {MAX_TOTAL_UPLOAD_BYTES // (1024 * 1024)} MB.",
                )
            if path.stat().st_size == 0:
                raise HTTPException(status_code=422, detail=f"Uploaded PDF is empty: {safe_filename}")
            _validate_pdf_signature(path, safe_filename)
            pdf_paths.append(path)

        try:
            course = course_engine.create_draft_from_pdfs(course_id, display_title, pdf_paths)
            if not course.competencies:
                course.competencies = course_engine.build_competency_map(course.chapters)
            course_store.save_new(course)
        except CourseGenerationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Course upload failed for %s", ", ".join(safe_filenames))
            raise HTTPException(status_code=500, detail="Course upload failed. Check backend logs.") from exc

    sections_count = len(course.all_sections())
    return CourseUploadResponse(
        course_id=course.course_id,
        title=course.title,
        status=course.status.value,
        chapters_count=len(course.chapters),
        sections_count=sections_count,
    )


@router.get("", response_model=CourseListResponse)
def list_courses() -> CourseListResponse:
    courses = []
    for course_id in course_store.list_course_ids():
        try:
            course = course_store.load(course_id)
            _ensure_course_plan(course)
            _enqueue_due_generation(course)
            courses.append(build_course_summary(course))
        except Exception:
            logger.exception("Could not load course %s", course_id)
    return CourseListResponse(courses=courses)


@router.get("/reviews/due", response_model=DueReviewsResponse)
def list_due_reviews(include_upcoming: bool = False) -> DueReviewsResponse:
    items: list[dict[str, Any]] = []
    for course_id in course_store.list_course_ids():
        course = course_store.load(course_id)
        _ensure_course_plan(course)
        items.extend(course_engine.due_review_items(course, include_upcoming=include_upcoming))
    return _due_reviews_response(items)


@router.get("/{course_id}", response_model=CourseDocument)
def get_course(course_id: str) -> CourseDocument:
    try:
        course = course_store.load(course_id)
        _ensure_course_plan(course)
        _enqueue_due_generation(course)
        return course
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{course_id}/reviews/due", response_model=DueReviewsResponse)
def get_course_due_reviews(course_id: str, include_upcoming: bool = False) -> DueReviewsResponse:
    course = _load_course(course_id, reconcile_generation=False)
    return _due_reviews_response(course_engine.due_review_items(course, include_upcoming=include_upcoming))


@router.get("/{course_id}/outline")
def get_outline(course_id: str) -> dict[str, Any]:
    course = _load_course(course_id)
    return {
        "course_id": course.course_id,
        "title": course.title,
        "status": course.status.value,
        "chapters": course.chapters,
    }


@router.put("/{course_id}/outline", response_model=CourseDocument)
def update_outline(course_id: str, request: OutlineUpdateRequest) -> CourseDocument:
    course = _load_course(course_id)
    course.chapters = _renumber_outline(request.chapters)
    course.competencies = course_engine.build_competency_map(course.chapters)
    _reset_course_generation(course)
    course_store.save(course)
    return course


@router.post("/{course_id}/generate", response_model=CourseDocument)
def generate_course(course_id: str) -> CourseDocument:
    course = _load_course(course_id)
    if not course.all_sections():
        raise HTTPException(status_code=422, detail="Approve an outline with at least one section before generation.")
    if all(section.status == CourseStatus.ready for section in course.all_sections()):
        _mark_generation_succeeded(course)
        course_store.save(course)
        return course

    _prepare_generation(course)
    course_store.save(course)
    _enqueue_generation(course.course_id)
    return _load_course(course_id)


@router.post("/{course_id}/sections/{section_id}/regenerate", response_model=CourseDocument)
def regenerate_course_section(course_id: str, section_id: str) -> CourseDocument:
    course = _load_course(course_id)
    try:
        section = course_engine.section_by_id(course, section_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not section.source_spans:
        raise HTTPException(status_code=422, detail="This section has no source text to regenerate from.")

    _reset_section_generation(section)
    _prepare_generation(course)
    course_store.save(course)
    _enqueue_generation(course.course_id)
    return _load_course(course_id)


@router.get("/{course_id}/sections/{section_id}")
def get_section(course_id: str, section_id: str) -> dict[str, Any]:
    course = _load_course(course_id)
    try:
        section = course_engine.section_by_id(course, section_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    competencies = [competency for competency in course.competencies if competency.id in section.competency_ids]
    return {"course_id": course.course_id, "course_title": course.title, "section": section, "competencies": competencies}


@router.post("/{course_id}/sections/{section_id}/chat", response_model=ChatResponse)
def chat_with_section(course_id: str, section_id: str, request: ChatRequest) -> ChatResponse:
    course = _load_course(course_id)
    try:
        section = course_engine.section_by_id(course, section_id)
        answer, support_status, source_refs = course_engine.chat(course, section_id, request.question, section.chat_history)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    turn = ChatTurn(
        question=request.question,
        answer=answer,
        support_status=support_status,
        source_refs=source_refs,
    )
    section.chat_history.append(turn)
    section.chat_history = section.chat_history[-30:]
    course_store.save(course)
    return ChatResponse(answer=answer, support_status=support_status.value, source_refs=source_refs, created_at=turn.created_at)


@router.post("/{course_id}/sections/{section_id}/checks/{check_id}/grade", response_model=CheckGradeResponse)
def grade_check(course_id: str, section_id: str, check_id: str, request: CheckGradeRequest) -> CheckGradeResponse:
    course = _load_course(course_id)
    try:
        section = course_engine.section_by_id(course, section_id)
        check = course_engine.check_by_id(section, check_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    score, feedback = course_engine.grade_answer(check.expected_answer, request.answer, request.confidence)
    check.last_score = score
    check.completed = score >= 70
    for concept in section.concepts:
        if concept.id in check.concept_ids:
            concept.mastery.mastery_percent = max(concept.mastery.mastery_percent, min(65, score))
            course_engine.record_mastery_review(concept.mastery, score, request.confidence)
    course_engine._sync_competency_mastery(course)
    _record_section_competency_review(course, section, score, request.confidence)
    course_store.save(course)
    return CheckGradeResponse(score=score, passed=check.completed, feedback=feedback)


@router.post("/{course_id}/sections/{section_id}/quiz/submit")
def submit_quiz(course_id: str, section_id: str, request: QuizSubmitRequest) -> dict[str, Any]:
    course = _load_course(course_id)
    try:
        section = course_engine.section_by_id(course, section_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    result = course_engine.submit_quiz(section, request.answers, request.confidence)
    course_engine._sync_competency_mastery(course)
    _record_section_competency_review(course, section, result["score"], request.confidence)
    course_store.save(course)
    return result


def _load_course(course_id: str, *, reconcile_generation: bool = True) -> CourseDocument:
    try:
        course = course_store.load(course_id)
        _ensure_course_plan(course)
        if reconcile_generation:
            _enqueue_due_generation(course)
        return course
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _ensure_course_plan(course: CourseDocument) -> None:
    if course.competencies:
        course_engine.repair_thin_lessons(course)
    else:
        course.competencies = course_engine.build_competency_map(course.chapters)
        course_engine.repair_thin_lessons(course)


def _record_section_competency_review(course: CourseDocument, section: SectionLesson, score: float, confidence: int) -> None:
    for competency in course.competencies:
        if competency.id in section.competency_ids or section.id in competency.lesson_ids:
            course_engine.record_mastery_review(competency.mastery, score, confidence)


def _due_reviews_response(items: list[dict[str, Any]]) -> DueReviewsResponse:
    due_count = sum(1 for item in items if item.get("due"))
    return DueReviewsResponse(
        items=[ReviewDueItem.model_validate(item) for item in items],
        due_count=due_count,
        upcoming_count=max(0, len(items) - due_count),
    )


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _retry_delay_seconds(attempts: int) -> float:
    exponent = max(0, attempts - 1)
    return min(GENERATION_RETRY_MAX_SECONDS, GENERATION_RETRY_BASE_SECONDS * (2**exponent))


def _prepare_generation(course: CourseDocument) -> None:
    total_sections = len(course.all_sections())
    completed_sections = sum(1 for section in course.all_sections() if section.status == CourseStatus.ready)
    course.status = CourseStatus.generating
    course.generation = CourseGenerationProgress(
        status=GenerationStatus.queued,
        total_sections=total_sections,
        completed_sections=completed_sections,
        failed_sections=0,
        attempts=0,
        max_attempts=GENERATION_MAX_ATTEMPTS,
        updated_at=_now_iso(),
    )


def _mark_generation_succeeded(course: CourseDocument) -> None:
    now = _now_iso()
    total_sections = len(course.all_sections())
    course.status = CourseStatus.ready
    course.generation.status = GenerationStatus.succeeded
    course.generation.total_sections = total_sections
    course.generation.completed_sections = total_sections
    course.generation.failed_sections = 0
    course.generation.next_retry_at = None
    course.generation.last_error = None
    course.generation.updated_at = now
    course.generation.finished_at = now


def _reset_course_generation(course: CourseDocument) -> None:
    if not course.competencies:
        course.competencies = course_engine.build_competency_map(course.chapters)
    for section in course.all_sections():
        _reset_section_generation(section)
    course.status = CourseStatus.outline_draft
    course.generation = CourseGenerationProgress(total_sections=len(course.all_sections()), updated_at=_now_iso())


def _reset_section_generation(section: SectionLesson) -> None:
    section.learning_objectives = []
    section.concepts = []
    section.lesson_blocks = []
    section.worked_examples = []
    section.checks = []
    section.mastery_quiz = []
    section.prerequisites = []
    section.completed = False
    section.status = CourseStatus.outline_draft
    section.chat_history = []


def _enqueue_generation(course_id: str, delay_seconds: float = 0) -> None:
    with _generation_lock:
        if course_id in _generation_running:
            return
        existing = _generation_jobs.get(course_id)
        if existing and existing.is_alive():
            return
        timer = threading.Timer(delay_seconds, _run_generation_job, args=(course_id,))
        timer.daemon = True
        _generation_jobs[course_id] = timer
        timer.start()


def _enqueue_due_generation(course: CourseDocument) -> None:
    if course.generation.status == GenerationStatus.running:
        with _generation_lock:
            is_running = course.course_id in _generation_running
        if not is_running:
            stored_course = course_store.load(course.course_id)
            stored_course.status = CourseStatus.generating
            stored_course.generation.status = GenerationStatus.queued
            stored_course.generation.updated_at = _now_iso()
            course.status = stored_course.status
            course.generation = stored_course.generation
            course_store.save(stored_course)
            _enqueue_generation(course.course_id)
        return
    if course.generation.status == GenerationStatus.queued:
        _enqueue_generation(course.course_id)
        return
    if course.generation.status != GenerationStatus.retry_scheduled or not course.generation.next_retry_at:
        return
    try:
        due_at = datetime.fromisoformat(course.generation.next_retry_at)
    except ValueError:
        _enqueue_generation(course.course_id)
        return
    if due_at <= datetime.now(UTC):
        _enqueue_generation(course.course_id)


def _run_generation_job(course_id: str) -> None:
    with _generation_lock:
        _generation_jobs.pop(course_id, None)
        if course_id in _generation_running:
            return
        _generation_running.add(course_id)

    retry_delay: float | None = None
    try:
        course = course_store.load(course_id)
        now = _now_iso()
        course.status = CourseStatus.generating
        course.generation.status = GenerationStatus.running
        course.generation.total_sections = len(course.all_sections())
        course.generation.completed_sections = sum(1 for section in course.all_sections() if section.status == CourseStatus.ready)
        course.generation.failed_sections = 0
        course.generation.attempts += 1
        course.generation.max_attempts = GENERATION_MAX_ATTEMPTS
        course.generation.next_retry_at = None
        course.generation.started_at = course.generation.started_at or now
        course.generation.updated_at = now
        course_store.save(course)

        def save_progress(progress_course: CourseDocument, _section: SectionLesson) -> None:
            progress_course.status = CourseStatus.generating
            progress_course.generation.status = GenerationStatus.running
            progress_course.generation.completed_sections = sum(
                1 for section in progress_course.all_sections() if section.status == CourseStatus.ready
            )
            progress_course.generation.total_sections = len(progress_course.all_sections())
            progress_course.generation.updated_at = _now_iso()
            course_store.save(progress_course)

        course_engine.generate_lessons(course, progress_callback=save_progress)
        if course.status == CourseStatus.ready:
            _mark_generation_succeeded(course)
        else:
            course.generation.status = GenerationStatus.failed
            course.generation.failed_sections = sum(1 for section in course.all_sections() if section.status == CourseStatus.needs_review)
            course.generation.last_error = "Some sections need source review before lesson generation can finish."
            course.generation.updated_at = _now_iso()
            course.generation.finished_at = course.generation.updated_at
        course_store.save(course)
    except CourseGenerationError as exc:
        retry_delay = _handle_generation_failure(course_id, str(exc))
    except Exception as exc:  # pragma: no cover - defensive job boundary
        logger.exception("Background course generation failed for %s", course_id)
        retry_delay = _handle_generation_failure(course_id, "Course generation failed. Check backend logs.")
    finally:
        with _generation_lock:
            _generation_running.discard(course_id)

    if retry_delay is not None:
        _enqueue_generation(course_id, retry_delay)


def _handle_generation_failure(course_id: str, message: str) -> float | None:
    course = course_store.load(course_id)
    attempts = max(1, course.generation.attempts)
    course.generation.total_sections = len(course.all_sections())
    course.generation.completed_sections = sum(1 for section in course.all_sections() if section.status == CourseStatus.ready)
    course.generation.failed_sections = sum(1 for section in course.all_sections() if section.status == CourseStatus.needs_review)
    course.generation.last_error = message
    course.generation.updated_at = _now_iso()

    if attempts < course.generation.max_attempts:
        delay = _retry_delay_seconds(attempts)
        course.status = CourseStatus.generating
        course.generation.status = GenerationStatus.retry_scheduled
        course.generation.next_retry_at = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat(timespec="seconds")
        course_store.save(course)
        return delay

    course.status = CourseStatus.needs_review
    course.generation.status = GenerationStatus.failed
    course.generation.next_retry_at = None
    course.generation.finished_at = course.generation.updated_at
    course_store.save(course)
    return None


def _validated_pdf_filename(file: UploadFile) -> str:
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Only PDF uploads are supported.")
    filename = Path(file.filename or "").name
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=422, detail="Upload must have a .pdf filename.")
    return filename


def _default_title(filenames: list[str]) -> str:
    if len(filenames) == 1:
        return Path(filenames[0]).stem
    return "Combined Course"


def _unique_temp_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        next_candidate = directory / f"{candidate.stem}_{index}{candidate.suffix}"
        if not next_candidate.exists():
            return next_candidate
        index += 1


async def _write_upload_file(file: UploadFile, destination: Path) -> int:
    total = 0
    with destination.open("wb") as handle:
        while chunk := await file.read(UPLOAD_CHUNK_SIZE):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Uploaded PDF is too large. Maximum size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.",
                )
            handle.write(chunk)
    return total


def _validate_pdf_signature(path: Path, filename: str) -> None:
    with path.open("rb") as handle:
        signature = handle.read(5)
    if signature != b"%PDF-":
        raise HTTPException(status_code=422, detail=f"Uploaded file is not a valid PDF: {filename}")


def _renumber_outline(chapters: list[Chapter]) -> list[Chapter]:
    for chapter_index, chapter in enumerate(chapters):
        chapter.order = chapter_index
        for section_index, section in enumerate(chapter.sections):
            section.chapter_id = chapter.id
            section.order = section_index
    return chapters
