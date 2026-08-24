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

The destructive diff/write phase (ChatTurn/TestAttempt clear, old-section
delete, new-section/chunk insert, course.status) is ONE all-or-nothing
transaction: nothing in that phase commits until the final line. report_progress
heartbeats during this phase use their OWN session precisely so they can
never accidentally commit it early — a mid-run failure must roll back to the
prior, fully-intact state, never leave old content destroyed with new
content half-written.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import html_conversion_enabled, pages_per_window, skill_map_autogen_enabled
from app.config import skip_front_matter as _skip_front_matter_enabled
from app.db.identity import section_id_for
from app.db.models import (
    Asset,
    ChatTurn,
    Chunk,
    ConceptEdge,
    ConceptMastery,
    ConceptMasteryEvent,
    ConceptSectionLink,
    ConceptSourceLink,
    Course,
    Highlight,
    Job,
    Note,
    PracticeAnswer,
    PracticeExtractionRun,
    PracticeQuestion,
    Section,
    Test,
    TestAttempt,
)
from app.pipeline._common import report_progress as _report_progress
from app.pipeline._common import (
    report_progress_in_session as _report_progress_in_session,
)
from app.pipeline.chunking import chunk_pages
from app.pipeline.extract import PdfExtractionError, open_pdf
from app.pipeline.html_conversion import html_dir
from app.pipeline.import_adapters import (
    PDF_FORMAT_NAME,
    PdfDocumentAdapter,
    UnsupportedSourceFormatError,
    choose_document_adapter,
    sniff_pdf_path,
    supported_adapters,
)
from app.pipeline.ingest_paths import images_dir_for_course
from app.services import search_index

_LOW_TEXT_YIELD_CHARS_PER_PAGE = 20
# Page-batch granularity for extraction-phase progress heartbeats — bounds
# the number of report_progress DB writes per asset regardless of document
# size (e.g. huge.pdf's 520 pages -> 26 heartbeats, not 520 or 1).
_EXTRACT_PROGRESS_BATCH_PAGES = 20


class IngestAllAssetsFailedError(Exception):
    pass


@dataclass
class _ExtractedAsset:
    asset: Asset
    document: Any


def _images_dir(course_id: str) -> Path:
    return images_dir_for_course(course_id)


def _asset_page_count(asset: Asset) -> int:
    """Cheap page-count-only open, used only to size the extraction-phase
    progress bar up front (app.pipeline.extract.open_pdf parses structure,
    not text — no markdown conversion happens here). Assets that fail to
    even open are left out of the total; the real extraction loop below
    re-attempts opening them and marks them extract_failed on its own, so
    nothing here needs to duplicate that handling.
    """
    path = Path(asset.stored_path)
    if not sniff_pdf_path(path):
        return 1
    doc = open_pdf(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def _document_adapter_for_asset(asset: Asset, *, on_batch=None):
    configured_pdf = PdfDocumentAdapter(
        window=pages_per_window(),
        skip_front_matter=_skip_front_matter_enabled(),
        on_batch=on_batch,
    )
    adapters = [
        configured_pdf,
        *[
            adapter
            for adapter in supported_adapters()
            if getattr(adapter, "format_name", None) != PDF_FORMAT_NAME
        ],
    ]
    return choose_document_adapter(
        asset,
        adapters=adapters,
    )


def _extract_one_asset(asset: Asset, *, on_batch=None) -> _ExtractedAsset:
    adapter = _document_adapter_for_asset(asset, on_batch=on_batch)
    document = adapter.extract(asset)
    page_count = int(document.metadata.get("page_count") or 0)

    asset.page_count = page_count
    asset.source_format = document.source_format
    asset.media_type = adapter.media_type
    total_chars = int(document.metadata.get("total_chars") or 0)
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

    return _ExtractedAsset(asset=asset, document=document)


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

    # REPLACED bucket semantics, same reasoning as REPLACED_ON_REINGEST
    # (app/db/registry.py): images are wholly regenerated every ingest, so
    # any image orphaned by a removed/changed asset (or by a page's image
    # count shrinking) never lingers. This is a non-transactional filesystem
    # side effect done up front, same risk tolerance already accepted for
    # per-asset bookkeeping commits below (see the loop's own comment) — if
    # a LATER stage of this ingest fails, the course ends up in
    # 'ingest_failed' regardless, a state the user must already recognize
    # and retry, which repopulates images fully again.
    images_dir = _images_dir(course_id)
    if images_dir.exists():
        shutil.rmtree(images_dir)

    # Same REPLACED reasoning as images_dir above: pdf2htmlEX output
    # (ADR-020) is a post-ingest enhancement. Unlike Section/Chunk, Asset
    # rows are NEVER deleted/recreated here (assets persist across
    # re-ingest — only their bookkeeping fields get updated below), so
    # html_status does NOT reset on its own just because the directory
    # was wiped; every asset's status is reset to 'none' explicitly so the
    # DB never claims 'ready'/'converting' for html output that no longer
    # exists on disk.
    html_dir_path = html_dir(course_id)
    if html_dir_path.exists():
        shutil.rmtree(html_dir_path)
    for asset in assets:
        asset.html_status = "none"

    # Sized up front so extraction progress is a real, global 0->80 measure
    # across every asset's pages, not a per-asset counter that resets (or
    # sits at 0 for the whole run when there's only one asset — the exact
    # bug this sizing pass exists to fix: a single-asset course used to
    # report pct=0 for the entire extraction, then jump straight to the
    # outlining stage once it finished).
    total_pages_all_assets = 0
    for asset in assets:
        try:
            total_pages_all_assets += _asset_page_count(asset)
        except (PdfExtractionError, UnsupportedSourceFormatError):
            pass

    extracted: list[_ExtractedAsset] = []
    pages_processed_so_far = 0
    for asset in assets:
        # Heartbeat BEFORE the (potentially slow) extraction call itself,
        # not just before the outline step after it — a long conversion on
        # a large PDF must not let the lease expire mid-extraction and get
        # the job requeued/double-run by the reconciler.
        _report_progress(
            job.id,
            stage="extracting",
            pct=int(80 * pages_processed_so_far / max(1, total_pages_all_assets)),
            message=f"extracting {asset.filename}",
        )

        def _on_batch(
            pages_done: int,
            total_pages: int,
            *,
            pages_processed_before_asset: int = pages_processed_so_far,
            filename: str = asset.filename,
        ) -> None:
            global_done = pages_processed_before_asset + pages_done
            _report_progress(
                job.id,
                stage="extracting",
                pct=int(80 * global_done / max(1, total_pages_all_assets)),
                message=f"extracting {filename} — page {pages_done} of {total_pages}",
            )

        try:
            extracted.append(_extract_one_asset(asset, on_batch=_on_batch))
            pages_processed_so_far += asset.page_count
        except (PdfExtractionError, UnsupportedSourceFormatError) as exc:
            asset.status = "extract_failed"
            asset.error = str(exc)
        # Per-asset commit is safe/desired here: these are non-destructive
        # updates to THIS asset's own bookkeeping fields (never touches
        # existing sections/cards/review-state), and are idempotent — a
        # re-run recomputes the same result. This is deliberately the ONLY
        # commit before the final one below; see run_ingest's docstring for
        # why the destructive diff/write phase must be one all-or-nothing
        # transaction.
        session.commit()

    if not extracted:
        # Raise (not return) so the standard run_ingest failure wrapper marks
        # the course ingest_failed AND fails the job with a clear error —
        # returning normally here used to leave the job 'succeeded' while the
        # course sat in 'ingest_failed', a dead end with no visible failure.
        # Each failed asset's status/error is already committed above, so
        # nothing informative is lost by this raise rolling back further.
        raise IngestAllAssetsFailedError(f"all {len(assets)} assets failed extraction")

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
    for item in extracted:
        # Extraction (the real bottleneck for a large PDF) already carried
        # the visible bar to 80 above; outlining is fast/deterministic
        # (no LLM, pure algorithm over already-extracted text), so it stays
        # flat at 80 rather than claiming its own sub-range — writing
        # (below) is what resumes the climb from 80 to 100.
        _report_progress(
            job.id,
            stage="outlining",
            pct=80,
            message=f"detecting outline for {item.asset.filename}",
        )
        for warning in item.document.warnings:
            _report_progress(
                job.id,
                stage="outlining",
                pct=80,
                message=f"{item.asset.filename}: {warning}",
            )

        for normalized_section in item.document.sections:
            occurrence = occurrence_counts.get(normalized_section.body_md, 0)
            occurrence_counts[normalized_section.body_md] = occurrence + 1
            section_id = section_id_for(course_id, normalized_section.body_md, occurrence)

            new_sections.append(
                {
                    "id": section_id,
                    "title": normalized_section.title,
                    "order_index": order_index,
                    "asset_id": normalized_section.asset_id,
                    "page_start": normalized_section.page_start,
                    "page_end": normalized_section.page_end,
                    "source_format": normalized_section.source_format,
                    "source_locator": normalized_section.source_locator.to_dict(),
                    "extractor_version": item.document.extractor_version,
                    "body_md": normalized_section.body_md,
                    "content_hash": normalized_section.content_hash,
                    "kind": normalized_section.kind,
                    "chapter_label": normalized_section.chapter_label,
                    "pages": normalized_section.pages,
                }
            )
            order_index += 1

    # From here on, EVERYTHING (deletes, inserts, course.status) is one
    # all-or-nothing transaction — no commit happens until the very end.
    # report_progress no longer touches this session (it uses its own), so
    # nothing below can accidentally persist a partial destructive write;
    # if anything raises, run_ingest's except-clause rolls the whole
    # destructive phase back and old content survives untouched.

    # Diff against existing sections by content-addressed id.
    existing_sections = {
        s.id: s for s in session.query(Section).filter(Section.course_id == course_id).all()
    }
    new_ids = {s["id"] for s in new_sections}
    removed_section_ids = set(existing_sections) - new_ids

    # Course-scoped, non-diffable generated history does not survive re-ingest
    # (per the derived-tables registry). Section-scoped learner state survives
    # naturally: notes/highlights/cards/review/progress hang off section_id or
    # card_id, which only disappear if their own section row is actually
    # deleted below.
    session.query(ChatTurn).filter(ChatTurn.course_id == course_id).delete()
    search_index.delete_course_documents(session, course_id, sync_fts=False)
    # TestAttempt before Test: TestAttempt.test_id -> Test.id is ON DELETE
    # CASCADE, so deleting Test first would already remove these via the
    # DB itself, but every REPLACED table gets its own explicit delete here
    # regardless (ADR-022) -- consistent with the rest of this block, not
    # relying on cascade ordering to do it implicitly.
    session.query(TestAttempt).filter(TestAttempt.course_id == course_id).delete()
    session.query(Test).filter(Test.course_id == course_id).delete()
    session.query(PracticeAnswer).filter(PracticeAnswer.course_id == course_id).delete()
    session.query(ConceptMasteryEvent).filter(ConceptMasteryEvent.course_id == course_id).delete()
    session.query(ConceptMastery).filter(ConceptMastery.course_id == course_id).delete()
    session.query(PracticeQuestion).filter(PracticeQuestion.course_id == course_id).delete()
    session.query(PracticeExtractionRun).filter(
        PracticeExtractionRun.course_id == course_id
    ).delete()
    # Legacy derived graph links are regenerated, but stable Concept anchors
    # are retained by the versioned curriculum layer below.
    session.query(ConceptEdge).filter(ConceptEdge.course_id == course_id).delete()
    session.query(ConceptSectionLink).filter(ConceptSectionLink.course_id == course_id).delete()
    # Stable curriculum anchors and published versions survive re-ingest.
    # Their exact historical source attribution must not silently jump to a
    # newly generated section, so links to removed content are marked stale;
    # the section FK becomes NULL via ON DELETE SET NULL below while the
    # source reference, excerpt, and content hash remain auditable.
    if removed_section_ids:
        (
            session.query(ConceptSourceLink)
            .filter(ConceptSourceLink.section_id.in_(removed_section_ids))
            .update({ConceptSourceLink.stale: True}, synchronize_session=False)
        )

    for existing_id, existing in list(existing_sections.items()):
        if existing_id not in new_ids:
            session.delete(existing)
    session.flush()

    total_new = len(new_sections)
    for i, data in enumerate(new_sections):
        # In-session (not report_progress): destructive deletes are already
        # pending on this session by this point — a second session trying to
        # commit here would contend for SQLite's single writer lock against
        # this session's still-open transaction. See report_progress_in_session's
        # docstring.
        _report_progress_in_session(
            job,
            stage="writing sections",
            pct=int(80 + 19 * i / max(1, total_new)),
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
            existing.asset_id = data["asset_id"]
            existing.page_start = data["page_start"]
            existing.page_end = data["page_end"]
            existing.source_format = data["source_format"]
            existing.source_locator = data["source_locator"]
            existing.extractor_version = data["extractor_version"]
            existing.kind = data["kind"]
            existing.chapter_label = data["chapter_label"]
            section_row = existing
            session.query(Chunk).filter(Chunk.section_id == section_row.id).delete()
        else:
            section_row = Section(
                id=data["id"],
                course_id=course_id,
                order_index=data["order_index"],
                title=data["title"],
                asset_id=data["asset_id"],
                page_start=data["page_start"],
                page_end=data["page_end"],
                source_format=data["source_format"],
                source_locator=data["source_locator"],
                body_md=data["body_md"],
                content_hash=data["content_hash"],
                lesson_status="none",
                extractor_version=data["extractor_version"],
                kind=data["kind"],
                chapter_label=data["chapter_label"],
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
        search_index.upsert_section_document(session, section_row, sync_fts=False)
        search_index.upsert_lesson_document(session, section_row, sync_fts=False)

    for note in session.query(Note).filter(Note.course_id == course_id).all():
        search_index.upsert_note_document(session, note, sync_fts=False)
    for highlight in session.query(Highlight).filter(Highlight.course_id == course_id).all():
        search_index.upsert_highlight_document(session, highlight, sync_fts=False)

    any_extracted_ok = any(a.status == "extracted" for a in assets)
    course.status = "ready" if any_extracted_ok else "ingest_failed"
    # Fire-and-forget enhancement (ADR-020): a separate durable job, added to
    # THIS session so it rides along with the same commit as everything
    # else above rather than needing its own round trip — ingest itself
    # must never slow down or fail because this is unavailable/misbehaving,
    # so this is nothing more than inserting a queued Job row.
    if any_extracted_ok and html_conversion_enabled():
        session.add(Job(type="convert_html", status="queued", payload={"course_id": course_id}))
    # Same fire-and-forget pattern, now for the skill map (ADR-030): auto-queue
    # concept extraction after a successful ingest. Ingest itself still makes
    # zero LLM calls — the durable worker runs this later — and a missing
    # provider surfaces as a cleanly failed job, never a failed ingest.
    if any_extracted_ok and skill_map_autogen_enabled():
        from app.services import curriculum_service

        curriculum_service.queue_extraction_in_session(session, course_id)
    search_index.rebuild_fts_if_present(session)
    _report_progress_in_session(job, stage="done", pct=100, message="ingest complete")
    session.commit()
