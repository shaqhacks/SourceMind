"""DB-backed library router — Task 11."""
from __future__ import annotations

import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from SourceMind.backend.extract.pdf import derive_title_from_pdf
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from SourceMind.backend.db import base, models
from SourceMind.backend.llm.provider import get_provider
from SourceMind.backend.pipeline import service
from SourceMind.backend.pipeline.retrieve import retrieve
from SourceMind.backend.services import review
from SourceMind.backend.services.anki_export import build_anki_tsv

router = APIRouter(prefix="/library", tags=["library"])

# Sentinel section_id for course-level chat turns (no specific chapter).
COURSE_CHAT_SECTION = "__course__"


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
    background_tasks: BackgroundTasks,
    title: str = Form(""),
    files: list[UploadFile] = File(...),
    provider=Depends(provider_dependency),
) -> dict:
    """Accept one or more PDFs and an OPTIONAL title; ingest runs in the background.

    Returns ``{course_id}`` immediately with the course in ``status="ingesting"``.
    The client polls ``GET /library/courses/{id}`` until ``status`` becomes
    ``needs_review`` (plan ready) or ``ingest_failed``. When no title is supplied
    it is derived from the first PDF's metadata title, falling back to its filename.
    """
    # Persist uploads to a temp dir the background job consumes and then cleans up.
    tmp_dir = Path(tempfile.mkdtemp())
    pdf_paths: list[Path] = []
    first_name = ""
    for upload in files:
        safe_name = Path(upload.filename or "upload.pdf").name
        if not first_name:
            first_name = safe_name
        dest = tmp_dir / safe_name
        dest.write_bytes(await upload.read())
        pdf_paths.append(dest)

    # Auto-derive a title from the PDF when the user didn't provide one.
    title = (title or "").strip()
    if not title and pdf_paths:
        title = derive_title_from_pdf(pdf_paths[0], first_name)
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
        service.run_ingest_job, course_id, title, pdf_paths, provider, tmp_dir,
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

    citations = [{"source_ref": r["source_ref"], "content": r["content"]} for r in results]

    system = (
        "Answer ONLY from the numbered sources; cite sources as [1],[2]; "
        "if they don't contain the answer, say so."
    )
    sources_block = "\n".join(
        f"[{i}] ({r['source_ref']}): {r['content']}" for i, r in enumerate(results, 1)
    )
    prompt = f"Sources:\n{sources_block}\n\nQuestion: {body.question}"

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
            .order_by(models.ChatTurn.created_at)
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
