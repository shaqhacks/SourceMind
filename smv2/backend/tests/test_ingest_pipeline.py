from __future__ import annotations

import time
from pathlib import Path

from app.db.engine import get_session
from app.db.models import Asset, Section
from conftest import _first_section_id

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pdfs"


def _upload(client, course_id: str, fixture_name: str):
    with (FIXTURES_DIR / fixture_name).open("rb") as f:
        return client.post(
            f"/api/courses/{course_id}/assets",
            files={"file": (fixture_name, f, "application/pdf")},
        )


def test_ingest_with_bookmarks_course_and_sections(client, ingest_course):
    course_id, _, _, claimed = ingest_course("with_bookmarks.pdf")
    assert claimed is True

    course = client.get(f"/api/courses/{course_id}").json()
    assert course["status"] == "ready"
    assert course["section_count"] == 3

    sections = client.get(f"/api/courses/{course_id}/sections").json()
    assert [s["title"] for s in sections] == [
        "Chapter 1: Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
    ]
    assert sections[0]["page_start"] == 1 and sections[0]["page_end"] == 4
    assert sections[1]["page_start"] == 5 and sections[1]["page_end"] == 8
    assert sections[2]["page_start"] == 9 and sections[2]["page_end"] == 12
    assert all(s["has_content"] for s in sections)
    assert all(s["word_count"] > 0 for s in sections)


def test_ingest_no_bookmarks_falls_back_to_page_windows(client, ingest_course):
    course_id, _, _, claimed = ingest_course("no_bookmarks.pdf")
    assert claimed is True

    sections = client.get(f"/api/courses/{course_id}/sections").json()
    # 10 pages, default window 12 -> exactly one window covering everything.
    assert len(sections) == 1
    assert sections[0]["page_start"] == 1
    assert sections[0]["page_end"] == 10
    assert sections[0]["title"] == "Pages 1–10"


def test_ingest_per_asset_isolation_continues_after_bad_asset(client):
    resp = client.post("/api/courses", json={"title": "Mixed Course"})
    course_id = resp.json()["id"]

    good = _upload(client, course_id, "with_bookmarks.pdf")
    bad = _upload(client, course_id, "encrypted.pdf")
    assert good.status_code == 201
    assert bad.status_code == 201

    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest_resp.status_code == 202

    from app.jobs.worker import run_due_jobs_once

    assert run_due_jobs_once() is True

    course = client.get(f"/api/courses/{course_id}").json()
    assert course["status"] == "ready"
    assert course["section_count"] == 3  # only the good asset's sections
    # A silently-dropped asset must still be visible once the course is
    # ready, not just discoverable by cross-referencing individual assets.
    assert course["failed_asset_count"] == 1

    session = get_session()
    try:
        good_asset = session.get(Asset, good.json()["id"])
        bad_asset = session.get(Asset, bad.json()["id"])
        assert good_asset.status == "extracted"
        assert bad_asset.status == "extract_failed"
        assert "password-protected" in bad_asset.error
    finally:
        session.close()


def test_ingest_all_assets_failing_marks_course_ingest_failed(client):
    resp = client.post("/api/courses", json={"title": "All Bad Course"})
    course_id = resp.json()["id"]

    upload_resp = _upload(client, course_id, "malformed.pdf")
    assert upload_resp.status_code == 201

    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest_resp.status_code == 202
    job_id = ingest_resp.json()["job_id"]

    from app.jobs.worker import run_due_jobs_once

    assert run_due_jobs_once() is True

    course = client.get(f"/api/courses/{course_id}").json()
    assert course["status"] == "ingest_failed"
    assert course["section_count"] == 0

    # The job itself must fail too, not silently 'succeed' while the course
    # sits in ingest_failed — a dead end with no visible failure signal.
    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert "all" in job["error"] and "failed extraction" in job["error"]


def test_reingest_mid_write_failure_rolls_back_fully_intact(client, ingest_course, monkeypatch):
    """A crash partway through the destructive write phase (after old
    ChatTurn/TestAttempt rows and stale sections are staged for deletion,
    mid-way through re-writing sections/chunks) must roll back to the
    PRIOR, fully-intact state — not leave old content destroyed with new
    content half-written. Cards/review-state hanging off an unchanged
    section (same content-addressed id) must survive too.
    """
    import app.pipeline.ingest as ingest_module
    from app.db.models import Card, ReviewState

    course_id, *_ = ingest_course("with_bookmarks.pdf")  # 3 sections
    section_id = _first_section_id(client, course_id)

    # Create referencing state that must survive an aborted re-ingest:
    # reading progress, plus a card + graded review state on the first section.
    progress_resp = client.put(
        f"/api/courses/{course_id}/progress", json={"section_id": section_id, "scroll_pos": 0.5}
    )
    assert progress_resp.status_code == 200

    session = get_session()
    try:
        section = session.get(Section, section_id)
        card = Card(
            id="fixed-test-card-id",
            course_id=course_id,
            section_id=section_id,
            front_md="Q",
            back_md="A",
            position=0,
        )
        session.add(card)
        session.commit()
    finally:
        session.close()
    assert client.post(f"/api/cards/{card.id}/grade", json={"grade": 3}).status_code == 200

    original_sections = client.get(f"/api/courses/{course_id}/sections").json()
    assert len(original_sections) == 3

    # Fail on the SECOND section written (of 3) — mid-phase, not at the
    # very start or very end.
    call_count = {"n": 0}
    real_chunk_pages = ingest_module.chunk_pages

    def _flaky_chunk_pages(pages):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("simulated mid-write crash")
        return real_chunk_pages(pages)

    monkeypatch.setattr(ingest_module, "chunk_pages", _flaky_chunk_pages)

    from app.jobs.worker import run_due_jobs_once

    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    job_id = ingest_resp.json()["job_id"]
    assert run_due_jobs_once() is True

    job = client.get(f"/api/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert "simulated mid-write crash" in job["error"]

    course = client.get(f"/api/courses/{course_id}").json()
    assert course["status"] == "ingest_failed"

    # Old sections fully intact — not partially destroyed/rewritten.
    sections_after = client.get(f"/api/courses/{course_id}/sections").json()
    assert sections_after == original_sections

    # Referencing state (progress, card + its review state) survived the
    # rolled-back re-ingest attempt untouched.
    progress = client.get(f"/api/courses/{course_id}/progress").json()
    assert progress["section_id"] == section_id
    assert progress["scroll_pos"] == 0.5

    session = get_session()
    try:
        assert session.get(Card, card.id) is not None
        assert session.get(ReviewState, card.id) is not None
    finally:
        session.close()


def test_ingest_scanned_pdf_does_not_crash_and_flags_low_text_yield(client, ingest_course):
    course_id, upload_resp, _, claimed = ingest_course("scanned.pdf")
    assert claimed is True

    course = client.get(f"/api/courses/{course_id}").json()
    assert course["status"] == "ready"

    session = get_session()
    try:
        asset = session.get(Asset, upload_resp.json()["id"])
        assert asset.status == "extracted"
        assert asset.error is not None and "scanned" in asset.error.lower()
        sections = session.query(Section).filter(Section.course_id == course_id).all()
        assert len(sections) >= 1
        assert all(not s.body_md.strip() for s in sections)
    finally:
        session.close()


def test_ingest_huge_pdf_completes_under_30_seconds(client, ingest_course):
    started = time.monotonic()
    course_id, _, _, claimed = ingest_course("huge.pdf")
    elapsed = time.monotonic() - started

    assert claimed is True
    assert elapsed < 30, f"huge.pdf ingest took {elapsed:.1f}s, expected < 30s"

    course = client.get(f"/api/courses/{course_id}").json()
    assert course["status"] == "ready"
    # 520 pages / 12 per window -> 44 windows (43 full + 1 partial of 4 pages).
    assert course["section_count"] == 44


def test_ingest_non_english_preserves_unicode_in_sections(client, ingest_course):
    course_id, _, _, claimed = ingest_course("non_english.pdf")
    assert claimed is True

    session = get_session()
    try:
        sections = session.query(Section).filter(Section.course_id == course_id).all()
        assert len(sections) == 1
        assert "Κεφάλαιο" in sections[0].body_md
        assert "Глава" in sections[0].body_md
    finally:
        session.close()


def test_ingest_two_identical_assets_get_distinct_section_ids(client):
    """Regression: occurrence counting must be course-scoped, not reset per
    asset — otherwise two assets with byte-identical text produce identical
    content-addressed section ids and the second INSERT violates the
    section primary key.
    """
    resp = client.post("/api/courses", json={"title": "Duplicate Assets Course"})
    course_id = resp.json()["id"]

    first = _upload(client, course_id, "with_bookmarks.pdf")
    second = _upload(client, course_id, "with_bookmarks.pdf")
    assert first.status_code == 201
    assert second.status_code == 201

    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest_resp.status_code == 202

    from app.jobs.worker import run_due_jobs_once

    assert run_due_jobs_once() is True

    course = client.get(f"/api/courses/{course_id}").json()
    assert course["status"] == "ready"
    assert course["section_count"] == 6  # 3 chapters x 2 identical assets

    session = get_session()
    try:
        section_ids = [
            s.id for s in session.query(Section).filter(Section.course_id == course_id).all()
        ]
        assert len(section_ids) == len(set(section_ids))  # all distinct, no collision
    finally:
        session.close()
