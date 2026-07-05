"""Ingest pipeline: zero-LLM, deterministic PDF -> sections -> chunks.

Called as the 'ingest' job handler (app/jobs/registry.py). Every step here
is deterministic — no LLM calls, ever. Per-asset extraction failures are
isolated: one bad PDF marks that asset extract_failed and the course
continues with the rest; the course only fails if every asset failed.

Idempotent by design: re-running ingest on the same course diffs the new
section set against the existing one by content-addressed id (identical
normalized text -> identical id), so unchanged sections and everything that
references them (review state, progress) survive untouched. Sections whose
text changed or that no longer exist are deleted (cascade cleans their
chunks/cards; ON DELETE SET NULL clears any progress_state pointing at
them); new sections are inserted. This is why the 'ingest' ON_ORPHAN hook
(app/jobs/registry.py) can safely just requeue instead of failing outright.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import pages_per_window
from app.db.identity import content_hash_for, normalize_text, section_id_for
from app.db.models import Asset, ChatTurn, Chunk, Course, Job, Section, TestAttempt, utcnow
from app.pipeline.chunking import chunk_pages
from app.pipeline.extract import PdfExtractionError, extract_markdown_pages, get_toc, open_pdf
from app.pipeline.outline_detect import detect_sections

_EXTRACTOR_ALGO_VERSION = "algo-1"
_LOW_TEXT_YIELD_CHARS_PER_PAGE = 20
# Lease extension while a long ingest job is heartbeating progress. Kept as
# a local constant (not imported from app.jobs.worker) to avoid a circular
# import — app.jobs.registry imports this module to register the 'ingest'
# handler, so this module must not import back from app.jobs.*.
_PROGRESS_LEASE_EXTENSION_SECONDS = 60


def extractor_version() -> str:
    try:
        pymupdf4llm_version = _pkg_version("pymupdf4llm")
    except PackageNotFoundError:
        pymupdf4llm_version = "unknown"
    return f"pymupdf4llm-{pymupdf4llm_version}+{_EXTRACTOR_ALGO_VERSION}"


def _report_progress(session: Session, job: Job, stage: str, pct: int, message: str) -> None:
    job.progress = {"stage": stage, "pct": pct, "message": message}
    job.lease_until = utcnow() + timedelta(seconds=_PROGRESS_LEASE_EXTENSION_SECONDS)
    session.commit()


@dataclass
class _ExtractedAsset:
    asset: Asset
    pages: list[str]  # markdown text per page, 0-based
    toc: list[tuple[int, str, int]]


def _extract_one_asset(asset: Asset) -> _ExtractedAsset:
    pdf_path = Path(asset.stored_path)
    doc = open_pdf(pdf_path)
    try:
        toc = get_toc(doc)
        pages = extract_markdown_pages(doc)
        page_count = doc.page_count
    finally:
        doc.close()

    asset.page_count = page_count
    total_chars = sum(len(p) for p in pages)
    avg_chars_per_page = (total_chars / page_count) if page_count else 0
    # Sparse text is not a failure — a scanned/image-only PDF still ingests,
    # it just produces thin sections. Flag it on the asset so the UI/ops can
    # tell the difference from a normal born-digital book.
    asset.error = (
        "low text yield — pages may be scanned/image-only"
        if avg_chars_per_page < _LOW_TEXT_YIELD_CHARS_PER_PAGE
        else None
    )
    asset.status = "extracted"

    return _ExtractedAsset(asset=asset, pages=pages, toc=toc)


def run_ingest(session: Session, job: Job, course_id: str) -> None:
    """Entry point: validates the course, then runs the actual pipeline
    under a safety net that guarantees course.status never gets stuck on
    'ingesting' — any unhandled exception marks it 'ingest_failed' before
    re-raising, so a crash mid-run always leaves a terminal, UI-visible
    status rather than an unrecoverable "still ingesting" that nothing else
    will ever clear.
    """
    course = session.get(Course, course_id)
    if course is None:
        raise ValueError(f"course not found: {course_id}")

    course.status = "ingesting"
    session.commit()

    try:
        _run_ingest(session, job, course_id)
    except Exception:
        session.rollback()
        failed_course = session.get(Course, course_id)
        if failed_course is not None:
            failed_course.status = "ingest_failed"
            session.commit()
        raise


def _run_ingest(session: Session, job: Job, course_id: str) -> None:
    course = session.get(Course, course_id)
    assert course is not None  # already validated by run_ingest

    assets = (
        session.query(Asset)
        .filter(Asset.course_id == course_id)
        .order_by(Asset.created_at.asc())
        .all()
    )
    if not assets:
        raise ValueError("course has no assets to ingest")

    window = pages_per_window()
    version_tag = extractor_version()

    extracted: list[_ExtractedAsset] = []
    total_assets = len(assets)
    for asset_idx, asset in enumerate(assets):
        # Heartbeat BEFORE the (potentially slow) extraction call itself,
        # not just before the outline step after it — a long conversion on
        # a large PDF must not let the lease expire mid-extraction and get
        # the job requeued/double-run by the reconciler.
        _report_progress(
            session,
            job,
            stage="extracting",
            pct=int(5 * asset_idx / max(1, total_assets)),
            message=f"extracting {asset.filename}",
        )
        try:
            extracted.append(_extract_one_asset(asset))
        except PdfExtractionError as exc:
            asset.status = "extract_failed"
            asset.error = str(exc)
        session.commit()

    if not extracted:
        course.status = "ingest_failed"
        session.commit()
        return

    # Build the full new section set up front (global order_index spans
    # every asset, sections sequential within each asset). occurrence_counts
    # is course-scoped, NOT per-asset: two assets with byte-identical
    # normalized text must still get distinct occurrence numbers (and thus
    # distinct section ids) from a single shared counter, or two duplicate
    # assets in one course collide on the same content-addressed id and the
    # second INSERT fails as a primary-key violation.
    new_sections: list[dict[str, Any]] = []
    order_index = 0
    occurrence_counts: dict[str, int] = {}
    total_extracted = len(extracted)
    for asset_idx, item in enumerate(extracted):
        _report_progress(
            session,
            job,
            stage="outlining",
            pct=int(10 + 30 * asset_idx / max(1, total_extracted)),
            message=f"detecting outline for {item.asset.filename}",
        )
        bounds_list = detect_sections(item.toc, len(item.pages), window)

        for bounds in bounds_list:
            page_slice = [(p, item.pages[p]) for p in range(bounds.page_start, bounds.page_end + 1)]
            body_md = "\n\n".join(text for _, text in page_slice if text and text.strip())
            normalized = normalize_text(body_md)

            occurrence = occurrence_counts.get(normalized, 0)
            occurrence_counts[normalized] = occurrence + 1
            section_id = section_id_for(course_id, normalized, occurrence)

            new_sections.append(
                {
                    "id": section_id,
                    "title": bounds.title,
                    "order_index": order_index,
                    "page_start": bounds.page_start,
                    "page_end": bounds.page_end,
                    "body_md": normalized,
                    "content_hash": content_hash_for(normalized),
                    "pages": page_slice,
                }
            )
            order_index += 1

    # Diff against existing sections by content-addressed id.
    existing_sections = {
        s.id: s for s in session.query(Section).filter(Section.course_id == course_id).all()
    }
    new_ids = {s["id"] for s in new_sections}

    # Course-scoped, non-diffable derived history does not survive re-ingest
    # (per the derived-tables registry). Review state / progress survive
    # naturally: they hang off card_id/section_id, which only disappear if
    # their own row is actually deleted below — no explicit "remap" step
    # needed beyond doing the section diff correctly.
    session.query(ChatTurn).filter(ChatTurn.course_id == course_id).delete()
    session.query(TestAttempt).filter(TestAttempt.course_id == course_id).delete()

    for existing_id, existing in list(existing_sections.items()):
        if existing_id not in new_ids:
            session.delete(existing)
    session.flush()

    total_new = len(new_sections)
    for i, data in enumerate(new_sections):
        _report_progress(
            session,
            job,
            stage="writing sections",
            pct=int(40 + 55 * i / max(1, total_new)),
            message=f"writing {data['title']}",
        )
        existing = existing_sections.get(data["id"])
        if existing is not None:
            # Same content-addressed id => identical normalized body_md by
            # construction. Only metadata can differ (title text before
            # normalization, position, extractor version) — body_md/
            # content_hash are never touched here.
            existing.title = data["title"]
            existing.order_index = data["order_index"]
            existing.page_start = data["page_start"]
            existing.page_end = data["page_end"]
            existing.extractor_version = version_tag
            section_row = existing
            session.query(Chunk).filter(Chunk.section_id == section_row.id).delete()
        else:
            section_row = Section(
                id=data["id"],
                course_id=course_id,
                order_index=data["order_index"],
                title=data["title"],
                page_start=data["page_start"],
                page_end=data["page_end"],
                body_md=data["body_md"],
                content_hash=data["content_hash"],
                lesson_status="none",
                extractor_version=version_tag,
            )
            session.add(section_row)
        session.flush()

        for chunk_index, tc in enumerate(chunk_pages(data["pages"])):
            session.add(
                Chunk(
                    course_id=course_id,
                    section_id=section_row.id,
                    chunk_index=chunk_index,
                    text=tc.text,
                    page=tc.page,
                    source_ref=f"{section_row.id}:p.{tc.page + 1}",
                )
            )

    any_extracted_ok = any(a.status == "extracted" for a in assets)
    course.status = "ready" if any_extracted_ok else "ingest_failed"
    _report_progress(session, job, stage="done", pct=100, message="ingest complete")
    session.commit()
