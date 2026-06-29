"""DB-backed library router — Task 11."""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from SourceMind.backend.extract.material import material_title

from SourceMind.backend.db import base, models
from SourceMind.backend.llm.provider import get_provider
from SourceMind.backend.pipeline import service
from SourceMind.backend.pipeline.retrieve import retrieve
from SourceMind.backend.services import review
from SourceMind.backend.services.anki_export import build_anki_tsv
from SourceMind.backend.services.grading import PASS_THRESHOLD, grade_quiz
from SourceMind.backend.services.ingest.security import sanitize_source
from SourceMind.backend.services.upload_validation import (
    MAGIC_PREFIX_LEN,
    UploadValidationError,
    validate_upload,
)

router = APIRouter(prefix="/library", tags=["library"])

# Sentinel section_id for course-level chat turns (no specific chapter).
COURSE_CHAT_SECTION = "__course__"

# ─── Hardening config (env-tunable, read per request) ─────────────────────────

_UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MiB streaming read granularity
_DEFAULT_MAX_UPLOAD_MB = 50.0
_DEFAULT_MAX_TOTAL_MB = 200.0
_DEFAULT_MAX_TEXT_CHARS = 1_000_000
_DEFAULT_MAX_CONCURRENT_LLM = 4


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _max_upload_bytes() -> int:
    return int(_env_float("SOURCEMIND_MAX_UPLOAD_MB", _DEFAULT_MAX_UPLOAD_MB) * 1024 * 1024)


def _max_total_bytes() -> int:
    return int(_env_float("SOURCEMIND_MAX_UPLOAD_TOTAL_MB", _DEFAULT_MAX_TOTAL_MB) * 1024 * 1024)


def _max_text_chars() -> int:
    return _env_int("SOURCEMIND_MAX_TEXT_CHARS", _DEFAULT_MAX_TEXT_CHARS)


# ─── In-process LLM concurrency guard ─────────────────────────────────────────
# A backstop, not full rate limiting: bound the number of in-flight LLM jobs so
# a burst of chat/generation requests can't exhaust workers. Single-instance
# only. Chat endpoints acquire non-blocking (fast 429 when saturated); the
# background generation job acquires blocking (it serializes rather than 429,
# since a background task cannot return a status code).
_LLM_SEMAPHORE = threading.BoundedSemaphore(
    _env_int("SOURCEMIND_MAX_CONCURRENT_LLM", _DEFAULT_MAX_CONCURRENT_LLM)
)
_LLM_BUSY_DETAIL = "Server busy: too many concurrent LLM requests. Please retry shortly."


@contextmanager
def _llm_slot(*, blocking: bool):
    """Acquire an LLM concurrency slot. Non-blocking acquire raises HTTP 429
    when saturated; blocking acquire waits for a free slot."""
    acquired = _LLM_SEMAPHORE.acquire(blocking=blocking)
    if not acquired:
        raise HTTPException(status_code=429, detail=_LLM_BUSY_DETAIL)
    try:
        yield
    finally:
        _LLM_SEMAPHORE.release()


def _generate_course_limited(course_id: str, *, provider) -> None:
    """Background generation wrapper bounded by the LLM concurrency guard."""
    with _llm_slot(blocking=True):
        service.generate_course(course_id, provider=provider)


def provider_dependency():
    """FastAPI dependency that returns the current LLM provider.

    Override in tests via::

        from SourceMind.backend.routers.library import provider_dependency
        app.dependency_overrides[provider_dependency] = lambda: StubProvider()
    """
    return get_provider()


def _slug(title: str) -> str:
    """Derive a filesystem-safe lowercase slug from *title*."""
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return slug or "course"


# ─── Request body models ──────────────────────────────────────────────────────


class ProgressBody(BaseModel):
    completed: bool


class ChatBody(BaseModel):
    question: str


class GradeBody(BaseModel):
    section_id: str
    card_index: int
    correct: bool | None = None
    quality: int | None = Field(default=None, ge=0, le=3)


class SectionTestBody(BaseModel):
    answers: list[int]


class CourseTestBody(BaseModel):
    answers: dict[str, list[int]]  # section_id -> list of answer indices


class SourceBody(BaseModel):
    kind: Literal["url", "text", "markdown", "youtube"]
    value: str
    title: str = ""


# ─── Upload / Ingest ──────────────────────────────────────────────────────────


@router.post("/uploads/source")
async def upload_source(
    body: SourceBody,
    background_tasks: BackgroundTasks,
    provider=Depends(provider_dependency),
) -> dict:
    """Accept a URL/text/markdown/youtube source; ingest in background.

    Returns ``{course_id}`` immediately with the course in ``status="ingesting"``.
    The client polls ``GET /library/courses/{id}`` until ``status`` becomes
    ``needs_review`` or ``ingest_failed``.
    """
    if body.kind in ("url", "youtube"):
        material: dict = {"kind": body.kind, "url": body.value}
    else:
        max_chars = _max_text_chars()
        if len(body.value) > max_chars:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Text source too large: {len(body.value)} characters "
                    f"(limit {max_chars})."
                ),
            )
        material = {"kind": body.kind, "text": body.value}
    materials = [material]

    title = body.title.strip()
    if not title:
        if body.kind in ("url", "youtube"):
            title = material_title(body.kind, url=body.value)
        elif body.kind == "text":
            title = "Pasted text"
        else:  # markdown
            title = "Markdown content"
    if not title:
        title = "Untitled Course"

    slug = _slug(title) or "course"
    course_id = slug
    with base.get_session() as session:
        if session.get(models.Course, course_id) is not None:
            course_id = f"{slug}_{uuid.uuid4().hex[:8]}"
        session.add(models.Course(
            id=course_id,
            title=title,
            status="ingesting",
            generation_status="idle",
        ))

    background_tasks.add_task(
        service.run_materials_job, course_id, title, materials, provider, None,
    )
    return {"course_id": course_id}


async def _write_upload_streamed(
    upload: UploadFile,
    dest: Path,
    *,
    safe_name: str,
    per_file_limit: int,
    total_so_far: int,
    total_limit: int,
) -> tuple[str, int]:
    """Stream *upload* to *dest* in chunks, enforcing size + type validation.

    Validates extension + magic bytes on the first chunk (fail fast before a
    large bogus file is buffered) and enforces both the per-file and cumulative
    size caps as bytes arrive. Returns ``(kind, bytes_written)``.

    Raises:
        ValueError: unsupported extension (from ``detect_kind``).
        UploadValidationError: content/extension magic mismatch.
        HTTPException(413): per-file or total size cap exceeded.
    """
    written = 0
    head = b""
    kind: str | None = None
    with dest.open("wb") as fh:
        while True:
            chunk = await upload.read(_UPLOAD_CHUNK_SIZE)
            if not chunk:
                break
            if kind is None:
                head = chunk[:MAGIC_PREFIX_LEN]
                kind = validate_upload(safe_name, head)  # ValueError / UploadValidationError
            written += len(chunk)
            if written > per_file_limit:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"File {safe_name!r} exceeds the per-file size limit "
                        f"({per_file_limit} bytes)."
                    ),
                )
            if total_so_far + written > total_limit:
                raise HTTPException(
                    status_code=413,
                    detail=f"Upload exceeds the total size limit ({total_limit} bytes).",
                )
            fh.write(chunk)
    if kind is None:  # empty file: still validate extension (+ empty magic)
        kind = validate_upload(safe_name, head)
    return kind, written


@router.post("/uploads")
async def upload_files(
    background_tasks: BackgroundTasks,
    title: str = Form(""),
    files: list[UploadFile] = File(...),
    provider=Depends(provider_dependency),
) -> dict:
    """Accept one or more files of any supported type and an OPTIONAL title; ingest runs in the background.

    Supported types: pdf, docx, pptx, txt, md. Unsupported extensions are
    rejected with 400, content/extension magic-byte mismatches with 415, and
    files exceeding the size caps (``SOURCEMIND_MAX_UPLOAD_MB`` per file,
    ``SOURCEMIND_MAX_UPLOAD_TOTAL_MB`` total) with 413 — all before any
    background job is scheduled. Returns ``{course_id}`` with the course in
    ``status="ingesting"``.
    """
    tmp_dir = Path(tempfile.mkdtemp())
    materials: list[dict] = []
    first_kind: str | None = None
    first_dest: Path | None = None

    per_file_limit = _max_upload_bytes()
    total_limit = _max_total_bytes()
    total_written = 0
    try:
        for idx, upload in enumerate(files):
            safe_name = Path(upload.filename or "upload").name
            # Finding 4: prefix each dest with its index so two files sharing the
            # same basename don't overwrite each other (silent data loss). The
            # extension is preserved, so validation on safe_name still works.
            dest = tmp_dir / f"{idx}_{safe_name}"
            kind, written = await _write_upload_streamed(
                upload,
                dest,
                safe_name=safe_name,
                per_file_limit=per_file_limit,
                total_so_far=total_written,
                total_limit=total_limit,
            )
            total_written += written
            materials.append({"kind": kind, "path": str(dest)})
            if first_kind is None:
                first_kind = kind
                # Title derivation must use the original (un-prefixed) name, not
                # the idx-prefixed dedup path, or the title gets a stray "0 " prefix.
                first_dest = tmp_dir / safe_name
    except UploadValidationError as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    except ValueError as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {exc}") from exc
    except Exception:
        # Includes HTTPException(413) from size caps — always clean up the temp dir.
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise

    # Auto-derive a title from the first material when the user didn't provide one.
    title = (title or "").strip()
    if not title and first_kind is not None and first_dest is not None:
        try:
            title = material_title(first_kind, path=first_dest, url=None)
        except Exception:
            pass
    if not title:
        title = "Untitled Course"

    slug = _slug(title) or "course"
    course_id = slug
    with base.get_session() as session:
        if session.get(models.Course, course_id) is not None:
            course_id = f"{slug}_{uuid.uuid4().hex[:8]}"
        # Placeholder row so the client can poll status while ingest runs.
        session.add(models.Course(
            id=course_id,
            title=title,
            status="ingesting",
            generation_status="idle",
        ))

    # Run extract -> outline -> plan off the request thread.
    background_tasks.add_task(
        service.run_materials_job, course_id, title, materials, provider, tmp_dir,
    )
    return {"course_id": course_id}


# ─── Course listing / detail ──────────────────────────────────────────────────


@router.get("/courses")
def list_courses() -> list[dict]:
    """Return a lightweight list of all courses."""
    with base.get_session() as session:
        courses = session.query(models.Course).all()
        return [
            {
                "id": c.id,
                "title": c.title,
                "status": c.status,
                "generation_status": c.generation_status,
                "generation_progress": c.generation_progress,
            }
            for c in courses
        ]


@router.get("/courses/{course_id}")
def get_course(course_id: str) -> dict:
    """Return course metadata, plan items, and lightweight chapter list."""
    with base.get_session() as session:
        course = session.get(models.Course, course_id)
        if course is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

        plan = (
            session.query(models.PlanItem)
            .filter_by(course_id=course_id)
            .order_by(models.PlanItem.order)
            .all()
        )
        chapters = session.query(models.Chapter).filter_by(course_id=course_id).all()

        # Build {section_id: order} map from plan items for stable sort.
        order_map: dict[str, int] = {
            p.section_id: (p.order if p.order is not None else 0)
            for p in plan
            if p.section_id is not None
        }

        # Build {section_id: completed} map from ProgressState rows.
        progress_rows = (
            session.query(models.ProgressState)
            .filter_by(course_id=course_id)
            .all()
        )
        completed_map: dict[str, bool] = {
            row.section_id: bool(row.completed)
            for row in progress_rows
            if row.section_id is not None
        }

        # Sort chapters by plan order; chapters absent from plan go last (stable).
        sorted_chapters = sorted(
            chapters,
            key=lambda ch: order_map.get(ch.section_id, float("inf")),
        )

        return {
            "course": {
                "id": course.id,
                "title": course.title,
                "status": course.status,
                "generation_status": course.generation_status,
                "generation_progress": course.generation_progress,
                "generation_last_error": course.generation_last_error,
            },
            "plan": [
                {
                    "section_id": p.section_id,
                    "title": p.title,
                    "objectives": p.objectives,
                    "importance": p.importance,
                    "prerequisites": p.prerequisites,
                    "target_words": p.target_words,
                    "order": p.order,
                }
                for p in plan
            ],
            "chapters": [
                {
                    "section_id": ch.section_id,
                    "title": ch.title,
                    "status": ch.status,
                    "importance": ch.importance,
                    "completed": completed_map.get(ch.section_id, False),
                }
                for ch in sorted_chapters
            ],
        }


@router.delete("/courses/{course_id}")
def delete_course(course_id: str) -> dict:
    """Delete a course and ALL of its associated rows + on-disk data.

    404 if the course doesn't exist.  Otherwise removes every child row
    (ChatTurn, ReviewState, ProgressState, Asset, Chapter, PlanItem) and the
    Course itself in one transaction, then removes the course's data dir.
    """
    with base.get_session() as session:
        course = session.get(models.Course, course_id)
        if course is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

        for child_model in (
            models.ChatTurn,
            models.ReviewState,
            models.ProgressState,
            models.Asset,
            models.Chapter,
            models.PlanItem,
        ):
            session.query(child_model).filter_by(course_id=course_id).delete()

        session.delete(course)

    # Remove the whole on-disk data dir for this course (assets dir's parent).
    shutil.rmtree(service.course_assets_dir(course_id).parent, ignore_errors=True)
    return {"deleted": True}


# ─── Plan ─────────────────────────────────────────────────────────────────────


@router.get("/courses/{course_id}/plan")
def get_plan(course_id: str) -> list[dict]:
    """Return the ordered plan items for a course."""
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

        plan = (
            session.query(models.PlanItem)
            .filter_by(course_id=course_id)
            .order_by(models.PlanItem.order)
            .all()
        )
        return [
            {
                "section_id": p.section_id,
                "title": p.title,
                "objectives": p.objectives,
                "importance": p.importance,
                "prerequisites": p.prerequisites,
                "target_words": p.target_words,
                "order": p.order,
            }
            for p in plan
        ]


@router.post("/courses/{course_id}/plan/approve")
def approve_plan_endpoint(course_id: str) -> dict:
    """Approve the plan and transition the course to generating."""
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

    service.approve_plan(course_id)
    return {"status": "generating"}


# ─── Generation ───────────────────────────────────────────────────────────────


@router.post("/courses/{course_id}/generate")
def generate_course_endpoint(
    course_id: str,
    background_tasks: BackgroundTasks,
    provider=Depends(provider_dependency),
) -> dict:
    """Schedule background generation; returns {status: started} immediately.

    In FastAPI's TestClient, BackgroundTasks run synchronously before the
    response is returned to test code, so tests can immediately GET the course
    to observe the completed generation state.
    """
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

    background_tasks.add_task(_generate_course_limited, course_id, provider=provider)
    return {"status": "started"}


# ─── Chapters ─────────────────────────────────────────────────────────────────


@router.get("/courses/{course_id}/chapters/{section_id}")
def get_chapter(course_id: str, section_id: str) -> dict:
    """Return the full chapter content for a section."""
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

        chapter = (
            session.query(models.Chapter)
            .filter_by(course_id=course_id, section_id=section_id)
            .first()
        )
        if chapter is None:
            raise HTTPException(status_code=404, detail=f"Chapter {section_id!r} not found")

        progress = (
            session.query(models.ProgressState)
            .filter_by(course_id=course_id, section_id=section_id)
            .first()
        )

        return {
            "section_id": chapter.section_id,
            "title": chapter.title,
            "objectives": chapter.objectives,
            "importance": chapter.importance,
            "source_pages": chapter.source_pages,
            "assets": chapter.assets,
            "body_md": chapter.body_md,
            "quiz": chapter.quiz,
            "cards": chapter.cards,
            "word_count": chapter.word_count,
            "status": chapter.status,
            "completed": bool(progress and progress.completed),
        }


# ─── Progress ─────────────────────────────────────────────────────────────────


@router.post("/courses/{course_id}/chapters/{section_id}/progress")
def update_progress(course_id: str, section_id: str, body: ProgressBody) -> dict:
    """Upsert a ProgressState row for a section."""
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

        prog = (
            session.query(models.ProgressState)
            .filter_by(course_id=course_id, section_id=section_id)
            .first()
        )
        now = datetime.now(timezone.utc).isoformat()
        if prog is None:
            prog = models.ProgressState(
                course_id=course_id,
                section_id=section_id,
                completed=body.completed,
                last_viewed_at=now,
            )
            session.add(prog)
        else:
            prog.completed = body.completed
            prog.last_viewed_at = now

        # flush to obtain autoincrement PK before session closes
        session.flush()
        return {
            "id": prog.id,
            "course_id": prog.course_id,
            "section_id": prog.section_id,
            "completed": prog.completed,
            "last_viewed_at": prog.last_viewed_at,
        }


# ─── Chat ─────────────────────────────────────────────────────────────────────


@router.post("/courses/{course_id}/chapters/{section_id}/chat")
def chat_with_chapter(
    course_id: str,
    section_id: str,
    body: ChatBody,
    provider=Depends(provider_dependency),
) -> dict:
    """Answer a question grounded in the chapter content; persist the exchange."""
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

        chapter = (
            session.query(models.Chapter)
            .filter_by(course_id=course_id, section_id=section_id)
            .first()
        )
        if chapter is None:
            raise HTTPException(status_code=404, detail=f"Chapter {section_id!r} not found")

        body_md = chapter.body_md or ""

    # Neutralize prompt-injection imperatives in the document-derived context
    # (NOT the user's question, which is legitimate user input).
    clean_body_md, _ = sanitize_source(body_md)

    prompt = (
        "You are a study assistant. Answer the question using ONLY the following "
        "chapter content. Do not introduce information not present in the chapter.\n\n"
        f"=== CHAPTER CONTENT ===\n{clean_body_md}\n\n"
        f"=== QUESTION ===\n{body.question}"
    )
    with _llm_slot(blocking=False):
        answer = provider.complete(prompt)
    if not isinstance(answer, str):
        answer = str(answer)

    now = datetime.now(timezone.utc).isoformat()
    with base.get_session() as session:
        session.add(models.ChatTurn(
            course_id=course_id,
            section_id=section_id,
            role="user",
            content=body.question,
            created_at=now,
        ))
        session.add(models.ChatTurn(
            course_id=course_id,
            section_id=section_id,
            role="assistant",
            content=answer,
            created_at=now,
        ))

    return {"answer": answer}


@router.post("/courses/{course_id}/chat")
def chat_with_course(
    course_id: str,
    body: ChatBody,
    provider=Depends(provider_dependency),
) -> dict:
    """Answer a question grounded in course chunks with citations; persist the exchange."""
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

        results = retrieve(session, course_id, body.question, k=6)

    # Neutralize prompt-injection imperatives in retrieved (document-derived)
    # chunk content before it is injected as context for the model.
    for r in results:
        r["content"] = sanitize_source(r.get("content") or "")[0]

    citations = [{"source_ref": r["source_ref"], "content": r["content"]} for r in results]

    system = (
        "Answer ONLY from the numbered sources; cite sources as [1],[2]; "
        "if they don't contain the answer, say so."
    )
    sources_block = "\n".join(
        f"[{i}] ({r['source_ref']}): {r['content']}" for i, r in enumerate(results, 1)
    )
    prompt = f"Sources:\n{sources_block}\n\nQuestion: {body.question}"

    with _llm_slot(blocking=False):
        answer = provider.complete(prompt, system=system)
    if not isinstance(answer, str):
        answer = str(answer)

    now = datetime.now(timezone.utc).isoformat()
    with base.get_session() as session:
        session.add(models.ChatTurn(
            course_id=course_id,
            section_id=COURSE_CHAT_SECTION,
            role="user",
            content=body.question,
            citations=None,
            created_at=now,
        ))
        session.add(models.ChatTurn(
            course_id=course_id,
            section_id=COURSE_CHAT_SECTION,
            role="assistant",
            content=answer,
            citations=citations,
            created_at=now,
        ))

    return {"answer": answer, "citations": citations}


@router.get("/courses/{course_id}/chat/history")
def course_chat_history(course_id: str) -> dict:
    """Return all course-level chat turns ordered by created_at ascending."""
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

        turns = (
            session.query(models.ChatTurn)
            .filter(
                models.ChatTurn.course_id == course_id,
                models.ChatTurn.section_id == COURSE_CHAT_SECTION,
            )
            .order_by(models.ChatTurn.created_at, models.ChatTurn.id)
            .all()
        )
        return {
            "history": [
                {
                    "role": t.role,
                    "content": t.content,
                    "citations": t.citations,
                    "created_at": t.created_at,
                }
                for t in turns
            ]
        }


# ─── Reviews ──────────────────────────────────────────────────────────────────


@router.get("/courses/{course_id}/reviews/due")
def get_due_reviews(course_id: str) -> list[dict]:
    """Return all due flashcard review rows for a course."""
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

        due = review.due_cards(session, course_id)
        return [
            {
                "id": r.id,
                "course_id": r.course_id,
                "section_id": r.section_id,
                "card_index": r.card_index,
                "ease": r.ease,
                "interval": r.interval,
                "due_at": r.due_at,
                "reps": r.reps,
            }
            for r in due
        ]


@router.post("/courses/{course_id}/reviews/grade")
def grade_review(course_id: str, body: GradeBody) -> dict:
    """Grade a flashcard and return the updated ReviewState."""
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

        row = review.grade_card(
            session, course_id, body.section_id, body.card_index,
            correct=body.correct, quality=body.quality,
        )
        return {
            "id": row.id,
            "course_id": row.course_id,
            "section_id": row.section_id,
            "card_index": row.card_index,
            "ease": row.ease,
            "interval": row.interval,
            "due_at": row.due_at,
            "reps": row.reps,
        }


# ─── Cross-course reviews + notifications ─────────────────────────────────────


@router.get("/reviews/due")
def get_due_reviews_all() -> list[dict]:
    """Return due flashcards across ALL courses, joined to card text + course title.

    Each item: ``{course_id, course_title, section_id, card_index, q, a, due_at}``.
    Cards whose ``card_index`` is out of range for their chapter are skipped.
    """
    with base.get_session() as session:
        due = review.due_cards_all(session)
        if not due:
            return []

        # Load each referenced chapter once: (course_id, section_id) -> cards list.
        pairs = {(r.course_id, r.section_id) for r in due}
        cards_by_pair: dict[tuple[str, str | None], list] = {}
        for course_id, section_id in pairs:
            chapter = (
                session.query(models.Chapter)
                .filter_by(course_id=course_id, section_id=section_id)
                .first()
            )
            cards_by_pair[(course_id, section_id)] = (
                chapter.cards if chapter and chapter.cards else []
            )

        # Map course_id -> title for the referenced courses.
        course_ids = {r.course_id for r in due}
        title_by_course: dict[str, str | None] = {
            c.id: c.title
            for c in session.query(models.Course)
            .filter(models.Course.id.in_(course_ids))
            .all()
        }

        out: list[dict] = []
        for r in due:
            cards = cards_by_pair.get((r.course_id, r.section_id)) or []
            idx = r.card_index
            if idx is None or idx < 0 or idx >= len(cards):
                continue
            card = cards[idx]
            out.append(
                {
                    "course_id": r.course_id,
                    "course_title": title_by_course.get(r.course_id),
                    "section_id": r.section_id,
                    "card_index": idx,
                    "q": card.get("q") if isinstance(card, dict) else None,
                    "a": card.get("a") if isinstance(card, dict) else None,
                    "due_at": r.due_at,
                }
            )
        return out


@router.get("/reviews/stats")
def get_review_stats() -> dict:
    """Return aggregate review statistics across all courses."""
    with base.get_session() as session:
        return review.review_stats(session)


@router.get("/notifications")
def get_notifications() -> dict:
    """Return a lightweight notification summary for the client poller.

    Shape: ``{due_review_count: int, courses: [{id, title, status,
    generation_progress}, ...]}`` — every course with its current status so the
    client can detect ready / needs_review / ingest_failed / generating.
    """
    with base.get_session() as session:
        due_review_count = len(review.due_cards_all(session))
        courses = session.query(models.Course).all()
        return {
            "due_review_count": due_review_count,
            "courses": [
                {
                    "id": c.id,
                    "title": c.title,
                    "status": c.status,
                    "generation_progress": c.generation_progress,
                }
                for c in courses
            ],
        }


# ─── Asset serving ────────────────────────────────────────────────────────────


@router.get("/courses/{course_id}/assets/{asset_path:path}")
def get_course_asset(course_id: str, asset_path: str) -> FileResponse:
    """Serve an extracted PDF asset image for a course.

    Path-traversal guard: resolves both the base assets directory and the
    requested target to their canonical absolute paths and rejects (403) any
    request whose target falls outside the assets directory.
    """
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

    base_dir = service.course_assets_dir(course_id).resolve()
    target = (base_dir / asset_path).resolve()

    if not target.is_relative_to(base_dir):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not target.exists():
        raise HTTPException(status_code=404, detail="Asset not found")

    return FileResponse(target)


# ─── Anki export ──────────────────────────────────────────────────────────────


@router.get("/courses/{course_id}/anki.tsv")
def export_anki(course_id: str) -> PlainTextResponse:
    """Return an Anki-importable 3-column TSV deck for a course."""
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

    tsv = build_anki_tsv(course_id)
    return PlainTextResponse(tsv, media_type="text/tab-separated-values")


# ─── Test mode endpoints ──────────────────────────────────────────────────────


@router.post("/courses/{course_id}/chapters/{section_id}/test/submit")
def submit_section_test(course_id: str, section_id: str, body: SectionTestBody) -> dict:
    """Grade a section test, persist a TestAttempt, return grade + attempt_id."""
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")
        chapter = (
            session.query(models.Chapter)
            .filter_by(course_id=course_id, section_id=section_id)
            .first()
        )
        if chapter is None:
            raise HTTPException(status_code=404, detail=f"Chapter {section_id!r} not found")

        quiz = chapter.quiz or []
        result = grade_quiz(quiz, body.answers)

        now = datetime.now(timezone.utc).isoformat()
        attempt = models.TestAttempt(
            course_id=course_id,
            section_id=section_id,
            scope="section",
            answers=body.answers,
            correct=result["correct"],
            total=result["total"],
            score=result["score"],
            passed=result["passed"],
            created_at=now,
        )
        session.add(attempt)
        session.flush()
        attempt_id = attempt.id

    return {**result, "attempt_id": attempt_id}


@router.get("/courses/{course_id}/chapters/{section_id}/test/attempts")
def get_section_test_attempts(course_id: str, section_id: str) -> list[dict]:
    """Return section test attempts newest first."""
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

        attempts = (
            session.query(models.TestAttempt)
            .filter_by(course_id=course_id, section_id=section_id, scope="section")
            .order_by(models.TestAttempt.id.desc())
            .all()
        )
        return [
            {
                "id": a.id,
                "score": a.score,
                "correct": a.correct,
                "total": a.total,
                "passed": a.passed,
                "created_at": a.created_at,
            }
            for a in attempts
        ]


@router.post("/courses/{course_id}/test/submit")
def submit_course_test(course_id: str, body: CourseTestBody) -> dict:
    """Grade a course-level test across all chapters with a quiz.

    body.answers is {section_id: [int, ...], ...}. Chapters that have a quiz
    but whose section_id is absent from body.answers are graded with an empty
    answers list (all wrong). Chapters without a quiz are skipped.
    Aggregates: correct = sum of per-section correct, total = sum of per-section total.
    """
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

        chapters = (
            session.query(models.Chapter)
            .filter_by(course_id=course_id)
            .all()
        )
        chapters_with_quiz = [ch for ch in chapters if ch.quiz]

        section_results = []
        total_correct = 0
        total_questions = 0
        for ch in chapters_with_quiz:
            answers_for_section = body.answers.get(ch.section_id, [])
            result = grade_quiz(ch.quiz, answers_for_section)
            total_correct += result["correct"]
            total_questions += result["total"]
            section_results.append({
                "section_id": ch.section_id,
                "title": ch.title,
                "score": result["score"],
                "correct": result["correct"],
                "total": result["total"],
                "passed": result["passed"],
            })

        agg_score = total_correct / total_questions if total_questions > 0 else 0.0
        agg_passed = agg_score >= PASS_THRESHOLD

        now = datetime.now(timezone.utc).isoformat()
        attempt = models.TestAttempt(
            course_id=course_id,
            section_id=None,
            scope="course",
            answers=body.answers,
            correct=total_correct,
            total=total_questions,
            score=agg_score,
            passed=agg_passed,
            created_at=now,
        )
        session.add(attempt)
        session.flush()
        attempt_id = attempt.id

    return {
        "score": agg_score,
        "correct": total_correct,
        "total": total_questions,
        "passed": agg_passed,
        "attempt_id": attempt_id,
        "sections": section_results,
    }


@router.get("/courses/{course_id}/test/attempts")
def get_course_test_attempts(course_id: str) -> list[dict]:
    """Return course-level test attempts (scope='course') newest first."""
    with base.get_session() as session:
        if session.get(models.Course, course_id) is None:
            raise HTTPException(status_code=404, detail=f"Course {course_id!r} not found")

        attempts = (
            session.query(models.TestAttempt)
            .filter_by(course_id=course_id, scope="course")
            .order_by(models.TestAttempt.id.desc())
            .all()
        )
        return [
            {
                "id": a.id,
                "score": a.score,
                "correct": a.correct,
                "total": a.total,
                "passed": a.passed,
                "created_at": a.created_at,
            }
            for a in attempts
        ]
