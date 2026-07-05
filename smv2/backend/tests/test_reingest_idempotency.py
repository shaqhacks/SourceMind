from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import fitz
import pytest

from app.db.engine import get_session
from app.db.models import Asset, Card, ProgressState, ReviewState, Section
from app.jobs.worker import run_due_jobs_once

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pdfs"


def _build_three_chapter_pdf(path: Path, chapter2_extra_line: str = "") -> None:
    """A small, self-contained 3-chapter bookmarked PDF (independent of the
    committed fixture corpus) so this test can control exactly one
    chapter's content between two ingest runs.
    """
    doc = fitz.open()
    chapters = [
        ("Chapter 1: Foundations", ["Standard chapter 1 content."]),
        (
            "Chapter 2: Structures",
            ["Standard chapter 2 content."] + ([chapter2_extra_line] if chapter2_extra_line else []),
        ),
        ("Chapter 3: Applications", ["Standard chapter 3 content."]),
    ]
    toc = []
    for i, (title, lines) in enumerate(chapters):
        toc.append([1, title, i + 1])
        page = doc.new_page()
        page.insert_text((72, 72), title, fontsize=12)
        y = 100
        for line in lines:
            page.insert_text((72, y), line, fontsize=11)
            y += 16
    doc.set_toc(toc)
    doc.save(str(path), no_new_id=1)
    doc.close()


def _sections_by_title(course_id: str) -> dict[str, Section]:
    session = get_session()
    try:
        rows = session.query(Section).filter(Section.course_id == course_id).all()
        return {s.title: s for s in rows}
    finally:
        session.close()


def _upload_and_ingest(client, course_id: str, pdf_path: Path) -> None:
    with pdf_path.open("rb") as f:
        resp = client.post(
            f"/api/courses/{course_id}/assets",
            files={"file": (pdf_path.name, f, "application/pdf")},
        )
    assert resp.status_code == 201
    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest_resp.status_code == 202
    assert run_due_jobs_once() is True


def test_reingest_replaces_not_duplicates(client, tmp_path):
    resp = client.post("/api/courses", json={"title": "Reingest Course"})
    course_id = resp.json()["id"]

    pdf_path = FIXTURES_DIR / "with_bookmarks.pdf"
    _upload_and_ingest(client, course_id, pdf_path)
    first_ids = {s.id for s in _sections_by_title(course_id).values()}
    assert len(first_ids) == 3

    # Seed review/progress state that must survive an identical re-ingest.
    session = get_session()
    try:
        section = session.query(Section).filter(Section.course_id == course_id).first()
        card = Card(
            id=str(uuid.uuid4())[:24],
            course_id=course_id,
            section_id=section.id,
            front_md="Q",
            back_md="A",
            position=0,
        )
        session.add(card)
        session.flush()
        session.add(
            ReviewState(
                card_id=card.id,
                course_id=course_id,
                due_at=datetime.now(timezone.utc),
                interval_days=1.0,
                ease=2.5,
                reps=0,
                lapses=0,
            )
        )
        session.add(ProgressState(course_id=course_id, section_id=section.id, scroll_pos=0.5))
        session.commit()
        card_id = card.id
    finally:
        session.close()

    # Re-ingest the exact same asset again via a fresh ingest job.
    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest_resp.status_code == 202
    assert run_due_jobs_once() is True

    second_ids = {s.id for s in _sections_by_title(course_id).values()}
    assert second_ids == first_ids

    session = get_session()
    try:
        assert session.get(Card, card_id) is not None
        assert session.get(ReviewState, card_id) is not None
        progress = session.get(ProgressState, course_id)
        assert progress is not None
        assert progress.section_id in first_ids
    finally:
        session.close()


def test_reingest_one_changed_section_resets_only_that(client, tmp_path):
    resp = client.post("/api/courses", json={"title": "Partial Reingest Course"})
    course_id = resp.json()["id"]

    pdf_path = tmp_path / "three_chapter.pdf"
    _build_three_chapter_pdf(pdf_path)
    _upload_and_ingest(client, course_id, pdf_path)

    before = _sections_by_title(course_id)
    assert set(before) == {"Chapter 1: Foundations", "Chapter 2: Structures", "Chapter 3: Applications"}

    # Overwrite the same asset's stored file with a version whose chapter 2
    # text differs — chapters 1 and 3 are byte-identical, so their
    # content-addressed ids must not change.
    session = get_session()
    try:
        asset = session.query(Asset).filter(Asset.course_id == course_id).one()
        stored_path = Path(asset.stored_path)
    finally:
        session.close()
    _build_three_chapter_pdf(stored_path, chapter2_extra_line="A brand new sentence.")

    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest_resp.status_code == 202
    assert run_due_jobs_once() is True

    after = _sections_by_title(course_id)
    assert after["Chapter 1: Foundations"].id == before["Chapter 1: Foundations"].id
    assert after["Chapter 3: Applications"].id == before["Chapter 3: Applications"].id
    assert after["Chapter 2: Structures"].id != before["Chapter 2: Structures"].id

    session = get_session()
    try:
        assert session.get(Section, before["Chapter 2: Structures"].id) is None
    finally:
        session.close()


def test_reingest_preserves_review_state_for_unchanged_section(client, tmp_path):
    resp = client.post("/api/courses", json={"title": "Review Survival Course"})
    course_id = resp.json()["id"]

    pdf_path = tmp_path / "three_chapter.pdf"
    _build_three_chapter_pdf(pdf_path)
    _upload_and_ingest(client, course_id, pdf_path)

    unchanged_section = _sections_by_title(course_id)["Chapter 1: Foundations"]

    session = get_session()
    try:
        card = Card(
            id=str(uuid.uuid4())[:24],
            course_id=course_id,
            section_id=unchanged_section.id,
            front_md="Q",
            back_md="A",
            position=0,
        )
        session.add(card)
        session.flush()
        session.add(
            ReviewState(
                card_id=card.id,
                course_id=course_id,
                due_at=datetime.now(timezone.utc),
                interval_days=3.0,
                ease=2.6,
                reps=2,
                lapses=0,
            )
        )
        session.add(
            ProgressState(course_id=course_id, section_id=unchanged_section.id, scroll_pos=0.75)
        )
        session.commit()
        card_id = card.id
    finally:
        session.close()

    session = get_session()
    try:
        asset = session.query(Asset).filter(Asset.course_id == course_id).one()
        stored_path = Path(asset.stored_path)
    finally:
        session.close()
    _build_three_chapter_pdf(stored_path, chapter2_extra_line="Only chapter 2 changes here.")

    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest_resp.status_code == 202
    assert run_due_jobs_once() is True

    session = get_session()
    try:
        review_state = session.get(ReviewState, card_id)
        assert review_state is not None
        assert review_state.reps == 2  # untouched by re-ingest
        assert session.get(Card, card_id) is not None  # card's own section still exists
        progress = session.get(ProgressState, course_id)
        assert progress is not None
        assert progress.section_id == unchanged_section.id
        assert progress.scroll_pos == pytest.approx(0.75)
    finally:
        session.close()


def test_reingest_clears_progress_section_id_when_that_section_is_removed(client, tmp_path):
    resp = client.post("/api/courses", json={"title": "Progress Cleared Course"})
    course_id = resp.json()["id"]

    pdf_path = tmp_path / "three_chapter.pdf"
    _build_three_chapter_pdf(pdf_path)
    _upload_and_ingest(client, course_id, pdf_path)

    changing_section = _sections_by_title(course_id)["Chapter 2: Structures"]

    session = get_session()
    try:
        session.add(
            ProgressState(course_id=course_id, section_id=changing_section.id, scroll_pos=0.3)
        )
        session.commit()
    finally:
        session.close()

    session = get_session()
    try:
        asset = session.query(Asset).filter(Asset.course_id == course_id).one()
        stored_path = Path(asset.stored_path)
    finally:
        session.close()
    _build_three_chapter_pdf(stored_path, chapter2_extra_line="This removes the old chapter 2 id.")

    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest_resp.status_code == 202
    assert run_due_jobs_once() is True

    session = get_session()
    try:
        progress = session.get(ProgressState, course_id)
        assert progress is not None  # row survives
        assert progress.section_id is None  # SET NULL, since chapter 2's old id is gone
    finally:
        session.close()
