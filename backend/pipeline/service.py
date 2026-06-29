"""Course orchestration service — ties PDF extraction, outline, plan, and
validated chapter generation to the database.

Public API (imported by the Task 11 API layer):
    ingest_pdfs(course_id, title, pdf_paths, provider, assets_dir) -> None
    approve_plan(course_id) -> None
    generate_course(course_id, provider, assets_dir) -> None
    regenerate_section(course_id, section_id, provider, assets_dir) -> None

Helper functions (also importable for unit testing):
    course_assets_dir(course_id) -> Path
    get_source_text(pages, page_start, page_end) -> str
    get_image_urls(assets, page_start, page_end, course_id) -> list[str]
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

from SourceMind.backend.db import base, models
from SourceMind.backend.extract.pdf import ExtractedPage, extract_pdf, extract_toc
from SourceMind.backend.llm.provider import LLMProvider, get_provider
from SourceMind.backend.pipeline.outline import detect_outline, sections_from_toc
from SourceMind.backend.pipeline.plan import PlanItem as PlanItemDC, generate_plan
from SourceMind.backend.pipeline.validate import generate_validated

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def course_assets_dir(course_id: str) -> Path:
    """Return the assets directory for a course (canonical, public API).

    Reads SOURCEMIND_ASSETS_DIR env var as the base; falls back to "data".
    Both the ingest pipeline and the HTTP asset-serving endpoint use this
    single source of truth.
    """
    base_dir = os.environ.get("SOURCEMIND_ASSETS_DIR", "data")
    return Path(base_dir) / course_id / "assets"


def _default_assets_dir(course_id: str) -> Path:
    """Backward-compat alias for course_assets_dir."""
    return course_assets_dir(course_id)


def _pages_file(assets_dir: Path) -> Path:
    """Return the path for the pages.json file (sibling of assets dir)."""
    return assets_dir.parent / "pages.json"


def _save_pages(pages: list[ExtractedPage], assets_dir: Path) -> None:
    """Persist page text mapping to pages.json for later retrieval."""
    data = {
        "pages": [
            {"page_number": p.page_number, "text": p.text}
            for p in pages
        ]
    }
    _pages_file(assets_dir).write_text(json.dumps(data, ensure_ascii=False))


def _load_pages(assets_dir: Path) -> list[ExtractedPage]:
    """Load page text mapping from pages.json."""
    raw = json.loads(_pages_file(assets_dir).read_text())
    return [
        ExtractedPage(page_number=entry["page_number"], text=entry["text"])
        for entry in raw["pages"]
    ]


# ---------------------------------------------------------------------------
# Public helpers (unit-testable, imported by tests)
# ---------------------------------------------------------------------------


def get_source_text(
    pages: list[ExtractedPage],
    page_start: int,
    page_end: int,
) -> str:
    """Return the joined text for pages within [page_start, page_end] inclusive."""
    parts = [p.text for p in pages if page_start <= p.page_number <= page_end]
    return "\n".join(parts)


def get_image_urls(
    assets: list,
    page_start: int,
    page_end: int,
    course_id: str = "",
) -> list[str]:
    """Return HTTP asset URLs for assets whose source_page falls within [page_start, page_end].

    Each URL has the form ``/library/courses/{course_id}/assets/{relpath}`` where
    *relpath* is the asset file's path relative to ``course_assets_dir(course_id)``.
    If the path cannot be made relative (e.g. it lives outside the assets dir),
    the basename is used as the relpath.  When *course_id* is empty the raw
    filesystem path is returned unchanged (legacy / test behaviour).

    Accepts both mapping-style inputs (plain dicts with ``"path"`` / ``"source_page"``
    keys, as produced by ``generate_course``'s asset_records list) and attribute-style
    objects (ORM ``Asset`` instances or any duck-typed object with ``.path`` /
    ``.source_page`` attributes).
    """
    def _get(a, key: str):
        return a[key] if isinstance(a, dict) else getattr(a, key)

    def _to_url(path_str: str) -> str:
        if not course_id:
            return path_str
        try:
            relpath = Path(path_str).relative_to(course_assets_dir(course_id)).as_posix()
        except ValueError:
            relpath = Path(path_str).name
        return f"/library/courses/{course_id}/assets/{relpath}"

    return [
        _to_url(_get(a, "path"))
        for a in assets
        if _get(a, "source_page") is not None
        and page_start <= _get(a, "source_page") <= page_end
    ]


# ---------------------------------------------------------------------------
# Core service functions
# ---------------------------------------------------------------------------


def ingest_pdfs(
    course_id: str,
    title: str,
    pdf_paths: list[Path],
    provider: LLMProvider | None = None,
    assets_dir: Path | None = None,
) -> None:
    """Extract PDFs, run outline + plan pipeline, persist Course/Plan/Chapter rows.

    Chapter rows are created as ``status="pending"`` placeholders so that
    ``generate_course`` can later find them by section_id and page range.

    Args:
        course_id:  Unique identifier for the course (used as DB primary key).
        title:      Human-readable course title.
        pdf_paths:  Ordered list of PDF file paths to ingest.
        provider:   LLM backend; defaults to ``get_provider()``.
        assets_dir: Directory for extracted images and pages.json.
                    Defaults to ``$SOURCEMIND_ASSETS_DIR/<course_id>/assets``
                    (falling back to ``data/<course_id>/assets``).
    """
    provider = provider or get_provider()

    if assets_dir is None:
        assets_dir = _default_assets_dir(course_id)
    assets_dir = Path(assets_dir)
    assets_dir.mkdir(parents=True, exist_ok=True)

    # --- Extract all PDFs with contiguous page numbers ---
    # Each source PDF extracts into its own subdir (src0/, src1/, ...) so that
    # per-PDF local image filenames (``page{i}_img{xref}.png``) cannot collide
    # across PDFs.  The contiguous global page-number offset is applied unchanged.
    all_pages: list[ExtractedPage] = []
    toc_entries: list[tuple[int, str, int]] = []
    offset = 0
    for idx, pdf_path in enumerate(pdf_paths):
        src_assets = assets_dir / f"src{idx}"
        src_assets.mkdir(parents=True, exist_ok=True)
        raw_pages = extract_pdf(Path(pdf_path), src_assets)
        # Collect this PDF's embedded TOC, mapped onto the global page numbering.
        for lvl, toc_title, pg in extract_toc(Path(pdf_path)):
            toc_entries.append((lvl, toc_title, pg + offset))
        for page in raw_pages:
            page.page_number = offset + page.page_number
        all_pages.extend(raw_pages)
        if raw_pages:
            offset = all_pages[-1].page_number + 1

    # Persist page texts for use by generate_course
    _save_pages(all_pages, assets_dir)

    # --- Outline: prefer the PDF's own table of contents (instant, accurate);
    # fall back to LLM-based detection only when the PDF has no bookmarks. ---
    sections = sections_from_toc(toc_entries, len(all_pages))
    if not sections:
        sections = detect_outline(all_pages, provider)
    plan_items = generate_plan(sections, all_pages, provider)
    section_map = {s.section_id: s for s in sections}

    # --- Persist to DB ---
    with base.get_session() as session:
        # Get-or-create: the upload handler may have already inserted a
        # placeholder row with status="ingesting" so the UI can poll.
        course = session.get(models.Course, course_id)
        if course is None:
            course = models.Course(id=course_id)
            session.add(course)
        course.title = title
        course.status = "needs_review"
        course.generation_status = "idle"

        # Asset rows for every extracted image
        for page in all_pages:
            for image_path in page.image_paths:
                asset = models.Asset(
                    id=str(uuid.uuid4()),
                    course_id=course_id,
                    path=str(image_path),
                    source_page=page.page_number,
                    caption="",
                )
                session.add(asset)

        # PlanItem rows + pending Chapter placeholders
        for idx, plan_dc in enumerate(plan_items):
            orm_plan = models.PlanItem(
                course_id=course_id,
                section_id=plan_dc.section_id,
                title=plan_dc.title,
                objectives=plan_dc.objectives,
                importance=plan_dc.importance,
                prerequisites=plan_dc.prerequisites,
                target_words=plan_dc.target_words,
                order=idx,
            )
            session.add(orm_plan)

            section = section_map.get(plan_dc.section_id)
            source_pages = (
                [section.page_start, section.page_end] if section else None
            )

            chapter = models.Chapter(
                course_id=course_id,
                section_id=plan_dc.section_id,
                title=plan_dc.title,
                objectives=plan_dc.objectives,
                importance=plan_dc.importance,
                source_pages=source_pages,
                status="pending",
            )
            session.add(chapter)


def run_ingest_job(
    course_id: str,
    title: str,
    pdf_paths: list[Path],
    provider: LLMProvider | None = None,
    cleanup_dir: Path | None = None,
) -> None:
    """Run ``ingest_pdfs`` as a background job.

    On any failure the course is marked ``status="ingest_failed"`` with the
    error recorded, so the UI can show a clear message instead of polling
    forever. The temporary upload directory (if given) is always removed.
    """
    try:
        ingest_pdfs(course_id, title, pdf_paths, provider=provider)
    except Exception as exc:  # noqa: BLE001 — surface any ingest failure to the UI
        with base.get_session() as session:
            course = session.get(models.Course, course_id)
            if course is None:
                course = models.Course(id=course_id, title=title)
                session.add(course)
            course.status = "ingest_failed"
            course.generation_last_error = str(exc)
    finally:
        if cleanup_dir is not None:
            shutil.rmtree(cleanup_dir, ignore_errors=True)


def approve_plan(course_id: str) -> None:
    """Mark a course as approved by setting ``status="generating"``."""
    with base.get_session() as session:
        course = session.get(models.Course, course_id)
        if course is not None:
            course.status = "generating"


def _generate_one_section(
    course_id: str,
    section_id: str,
    plan_records: list[dict],
    asset_records: list[dict],
    pages: list[ExtractedPage],
    provider: LLMProvider,
) -> None:
    """Generate and persist a single chapter section.

    Raises any exception from ``generate_validated`` so the caller can handle
    per-section failures.
    """
    plan_rec = next(
        (p for p in plan_records if p["section_id"] == section_id), None
    )
    if plan_rec is None:
        raise ValueError(f"No plan record found for section_id={section_id!r}")

    # Load chapter source_pages from DB
    with base.get_session() as session:
        chap = (
            session.query(models.Chapter)
            .filter_by(course_id=course_id, section_id=section_id)
            .first()
        )
        source_pages = (chap.source_pages or [0, 0]) if chap else [0, 0]

    page_start, page_end = source_pages[0], source_pages[1]
    source_text = get_source_text(pages, page_start, page_end)
    image_urls = get_image_urls(asset_records, page_start, page_end, course_id=course_id)
    had_figures = len(image_urls) > 0

    plan_dc = PlanItemDC(
        section_id=plan_rec["section_id"],
        title=plan_rec["title"] or "",
        objectives=plan_rec["objectives"],
        importance=plan_rec["importance"],
        prerequisites=plan_rec["prerequisites"],
        target_words=plan_rec["target_words"],
    )

    draft = generate_validated(
        plan_dc,
        source_text,
        image_urls,
        provider,
        had_figures=had_figures,
    )

    with base.get_session() as session:
        chap = (
            session.query(models.Chapter)
            .filter_by(course_id=course_id, section_id=section_id)
            .first()
        )
        if chap is not None:
            chap.body_md = draft.body_md
            chap.quiz = draft.quiz
            chap.cards = draft.cards
            chap.word_count = draft.word_count
            chap.status = "ready"

        # Seed ReviewState rows so the SRS queue is immediately populated.
        # Delete first for idempotency (e.g. regeneration won't duplicate rows).
        session.query(models.ReviewState).filter_by(
            course_id=course_id, section_id=section_id
        ).delete()
        for i, _card in enumerate(draft.cards):
            session.add(models.ReviewState(
                course_id=course_id,
                section_id=section_id,
                card_index=i,
                ease=2.5,
                interval=0,
                due_at="",
                reps=0,
            ))


def generate_course(
    course_id: str,
    provider: LLMProvider | None = None,
    assets_dir: Path | None = None,
) -> None:
    """Generate all pending/failed chapter sections for a course.

    Resumes from where a previous run left off (skips sections already
    ``status="ready"``).  Sets ``generation_status`` to ``"succeeded"`` or
    ``"failed"`` based on per-section outcomes, and sets the course
    ``status`` to ``"ready"`` only when every section succeeded, otherwise
    ``"failed"``.

    Args:
        course_id:  Course to generate.
        provider:   LLM backend; defaults to ``get_provider()``.
        assets_dir: Directory containing pages.json (parent of assets/).
                    Defaults to ``$SOURCEMIND_ASSETS_DIR/<course_id>/assets``.
    """
    provider = provider or get_provider()

    if assets_dir is None:
        assets_dir = _default_assets_dir(course_id)
    assets_dir = Path(assets_dir)

    # --- Load all data into plain dicts before session closes ---
    plan_records: list[dict] = []
    chapter_statuses: dict[str, str] = {}
    asset_records: list[dict] = []

    with base.get_session() as session:
        plan_items = (
            session.query(models.PlanItem)
            .filter_by(course_id=course_id)
            .order_by(models.PlanItem.order)
            .all()
        )
        for pi in plan_items:
            plan_records.append({
                "section_id": pi.section_id,
                "title": pi.title,
                "objectives": list(pi.objectives or []),
                "importance": pi.importance or "supporting",
                "prerequisites": list(pi.prerequisites or []),
                "target_words": pi.target_words or 0,
            })

        chapters = (
            session.query(models.Chapter).filter_by(course_id=course_id).all()
        )
        for ch in chapters:
            chapter_statuses[ch.section_id] = ch.status or "pending"

        assets = (
            session.query(models.Asset).filter_by(course_id=course_id).all()
        )
        for a in assets:
            asset_records.append({"path": a.path, "source_page": a.source_page})

        total = len(plan_records)

        # Set running status
        course = session.get(models.Course, course_id)
        if course is not None:
            course.generation_status = "running"
            course.generation_progress = {
                "total": total,
                "completed": 0,
                "failed": 0,
            }

    # Load pages from pages.json
    pages = _load_pages(assets_dir)

    completed = 0
    failed = 0

    for plan_rec in plan_records:
        section_id = plan_rec["section_id"]

        if chapter_statuses.get(section_id) == "ready":
            completed += 1
            _update_progress(course_id, total, completed, failed)
            continue

        try:
            _generate_one_section(
                course_id,
                section_id,
                plan_records,
                asset_records,
                pages,
                provider,
            )
            completed += 1
            _update_progress(course_id, total, completed, failed)

        except Exception as exc:
            failed += 1
            _update_progress(
                course_id,
                total,
                completed,
                failed,
                last_error=str(exc),
                failed_section_id=section_id,
            )

    # Final status
    with base.get_session() as session:
        course = session.get(models.Course, course_id)
        if course is not None:
            course.generation_status = "succeeded" if failed == 0 else "failed"
            course.status = "ready" if failed == 0 else "failed"
            course.generation_progress = {
                "total": total,
                "completed": completed,
                "failed": failed,
            }


def _update_progress(
    course_id: str,
    total: int,
    completed: int,
    failed: int,
    last_error: str | None = None,
    failed_section_id: str | None = None,
) -> None:
    """Persist generation progress and optionally mark a chapter as failed."""
    with base.get_session() as session:
        course = session.get(models.Course, course_id)
        if course is not None:
            course.generation_progress = {
                "total": total,
                "completed": completed,
                "failed": failed,
            }
            if last_error is not None:
                course.generation_last_error = last_error

        if failed_section_id is not None:
            chap = (
                session.query(models.Chapter)
                .filter_by(course_id=course_id, section_id=failed_section_id)
                .first()
            )
            if chap is not None:
                chap.status = "failed"


def regenerate_section(
    course_id: str,
    section_id: str,
    provider: LLMProvider | None = None,
    assets_dir: Path | None = None,
) -> None:
    """Reset a single chapter section to pending and regenerate it.

    Args:
        course_id:  Course containing the section.
        section_id: Section to regenerate.
        provider:   LLM backend; defaults to ``get_provider()``.
        assets_dir: Directory containing pages.json (parent of assets/).
                    Defaults to ``$SOURCEMIND_ASSETS_DIR/<course_id>/assets``.
    """
    provider = provider or get_provider()

    if assets_dir is None:
        assets_dir = _default_assets_dir(course_id)
    assets_dir = Path(assets_dir)

    # Reset chapter to pending
    with base.get_session() as session:
        chap = (
            session.query(models.Chapter)
            .filter_by(course_id=course_id, section_id=section_id)
            .first()
        )
        if chap is not None:
            chap.status = "pending"
            chap.body_md = None
            chap.quiz = None
            chap.cards = None

    # Load plan and asset records
    plan_records: list[dict] = []
    asset_records: list[dict] = []

    with base.get_session() as session:
        plan_items = (
            session.query(models.PlanItem)
            .filter_by(course_id=course_id)
            .order_by(models.PlanItem.order)
            .all()
        )
        for pi in plan_items:
            plan_records.append({
                "section_id": pi.section_id,
                "title": pi.title,
                "objectives": list(pi.objectives or []),
                "importance": pi.importance or "supporting",
                "prerequisites": list(pi.prerequisites or []),
                "target_words": pi.target_words or 0,
            })

        assets = (
            session.query(models.Asset).filter_by(course_id=course_id).all()
        )
        for a in assets:
            asset_records.append({"path": a.path, "source_page": a.source_page})

    pages = _load_pages(assets_dir)

    # Mirror generate_course's per-section handling: on failure mark the
    # chapter "failed" and record the error rather than re-raising, so the
    # API can poll status instead of seeing the chapter stuck "pending".
    try:
        _generate_one_section(
            course_id,
            section_id,
            plan_records,
            asset_records,
            pages,
            provider,
        )
    except Exception as exc:
        with base.get_session() as session:
            chap = (
                session.query(models.Chapter)
                .filter_by(course_id=course_id, section_id=section_id)
                .first()
            )
            if chap is not None:
                chap.status = "failed"
            course = session.get(models.Course, course_id)
            if course is not None:
                course.generation_last_error = str(exc)
