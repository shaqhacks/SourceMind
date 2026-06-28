"""DB-backed library router — Task 11."""
from __future__ import annotations

import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from SourceMind.backend.db import base, models
from SourceMind.backend.llm.provider import get_provider
from SourceMind.backend.pipeline import service
from SourceMind.backend.services import review
from SourceMind.backend.services.anki_export import build_anki_tsv

router = APIRouter(prefix="/library", tags=["library"])


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
    correct: bool


# ─── Upload / Ingest ──────────────────────────────────────────────────────────


@router.post("/uploads")
async def upload_pdfs(
    title: str = Form(...),
    files: list[UploadFile] = File(...),
    provider=Depends(provider_dependency),
) -> dict:
    """Accept one or more PDFs plus a title, run ingest, and return course_id."""
    slug = _slug(title)
    course_id = slug

    # Ensure uniqueness: if a course with this slug already exists, append a suffix.
    with base.get_session() as session:
        if session.get(models.Course, course_id) is not None:
            course_id = f"{slug}_{uuid.uuid4().hex[:8]}"

    tmp_dir = Path(tempfile.mkdtemp())
    pdf_paths: list[Path] = []
    for upload in files:
        safe_name = Path(upload.filename or "upload.pdf").name
        dest = tmp_dir / safe_name
        dest.write_bytes(await upload.read())
        pdf_paths.append(dest)

    service.ingest_pdfs(course_id, title, pdf_paths, provider=provider)
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

    background_tasks.add_task(service.generate_course, course_id, provider=provider)
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

    prompt = (
        "You are a study assistant. Answer the question using ONLY the following "
        "chapter content. Do not introduce information not present in the chapter.\n\n"
        f"=== CHAPTER CONTENT ===\n{body_md}\n\n"
        f"=== QUESTION ===\n{body.question}"
    )
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
            session, course_id, body.section_id, body.card_index, body.correct
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
