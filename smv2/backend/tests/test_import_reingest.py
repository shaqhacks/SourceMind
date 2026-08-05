from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.config import data_dir
from app.db.engine import get_session
from app.db.models import (
    Asset,
    Card,
    Highlight,
    Note,
    ProgressState,
    ReviewState,
    Section,
)
from app.jobs.worker import run_due_jobs_once
from conftest import _course_profile_id


def _create_course(client, title: str = "Import Reingest Course") -> str:
    response = client.post("/api/courses", json={"title": title})
    assert response.status_code == 201
    return response.json()["id"]


def _upload_markdown(client, course_id: str, content: bytes, filename: str = "course.md") -> str:
    response = client.post(
        f"/api/courses/{course_id}/assets",
        files={"file": (filename, content, "text/markdown")},
    )
    assert response.status_code == 201
    return response.json()["id"]


def _run_ingest(client, course_id: str) -> None:
    response = client.post(f"/api/courses/{course_id}/ingest")
    assert response.status_code == 202
    assert run_due_jobs_once() is True


def _sections_by_title(course_id: str) -> dict[str, Section]:
    session = get_session()
    try:
        rows = session.query(Section).filter(Section.course_id == course_id).all()
        return {section.title: section for section in rows}
    finally:
        session.close()


def _replace_asset_bytes(course_id: str, content: bytes) -> None:
    session = get_session()
    try:
        asset = session.query(Asset).filter(Asset.course_id == course_id).one()
        Path(asset.stored_path).write_bytes(content)
        asset.size_bytes = len(content)
        asset.sha256 = hashlib.sha256(content).hexdigest()
        asset.status = "stored"
        asset.error = None
        session.commit()
    finally:
        session.close()


def test_reingest_keeps_section_ids_and_locators_for_unchanged_markdown(client, monkeypatch):
    """Catches treating adapter-produced locators as section identity."""
    monkeypatch.setenv("SMV2_IMPORT_MARKDOWN_EXPERIMENTAL", "1")
    course_id = _create_course(client)
    body = b"# Stable One\n\nSame text.\n\n# Stable Two\n\nAlso same text.\n"
    _upload_markdown(client, course_id, body)
    _run_ingest(client, course_id)

    before = {
        title: (section.id, section.source_locator)
        for title, section in _sections_by_title(course_id).items()
    }

    _run_ingest(client, course_id)

    after = {
        title: (section.id, section.source_locator)
        for title, section in _sections_by_title(course_id).items()
    }
    assert after == before


def test_reingest_changes_only_changed_section_and_preserves_surviving_state(
    client, monkeypatch
):
    """Catches course-wide reset of section-scoped learner state."""
    monkeypatch.setenv("SMV2_IMPORT_MARKDOWN_EXPERIMENTAL", "1")
    course_id = _create_course(client)
    first = b"# Alpha\n\nAlpha body.\n\n# Beta\n\nBeta body.\n\n# Gamma\n\nGamma body.\n"
    changed = (
        b"# Alpha\n\nAlpha body.\n\n# Beta\n\nBeta body changed.\n\n# Gamma\n\nGamma body.\n"
    )
    _upload_markdown(client, course_id, first)
    _run_ingest(client, course_id)
    before = _sections_by_title(course_id)
    alpha = before["Alpha"]

    session = get_session()
    try:
        profile_id = _course_profile_id(session, course_id)
        card = Card(
            id="alpha-card",
            course_id=course_id,
            section_id=alpha.id,
            front_md="front",
            back_md="back",
            position=0,
        )
        session.add(card)
        session.flush()
        session.add(
            ReviewState(
                course_learning_profile_id=profile_id,
                card_id=card.id,
                course_id=course_id,
                due_at=datetime.now(timezone.utc),
                interval_days=4.0,
                ease=2.7,
                reps=3,
                lapses=1,
            )
        )
        session.add(ProgressState(course_id=course_id, section_id=alpha.id, scroll_pos=0.42))
        session.commit()
    finally:
        session.close()

    _replace_asset_bytes(course_id, changed)
    _run_ingest(client, course_id)
    after = _sections_by_title(course_id)

    assert after["Alpha"].id == before["Alpha"].id
    assert after["Alpha"].source_locator == before["Alpha"].source_locator
    assert after["Gamma"].id == before["Gamma"].id
    assert after["Gamma"].source_locator == before["Gamma"].source_locator
    assert after["Beta"].id != before["Beta"].id
    assert after["Beta"].source_locator == {
        "type": "heading",
        "asset_id": alpha.asset_id,
        "heading_path": ["Beta"],
    }

    session = get_session()
    try:
        assert session.get(Card, "alpha-card") is not None
        review = session.get(ReviewState, (profile_id, "alpha-card"))
        assert review is not None
        assert review.reps == 3
        progress = session.get(ProgressState, course_id)
        assert progress is not None
        assert progress.section_id == alpha.id
        assert progress.scroll_pos == 0.42
    finally:
        session.close()


def test_reingest_preserves_surviving_annotations_and_rebuilds_search(client, monkeypatch):
    """Catches wiping annotations or failing to rebuild their search rows."""
    monkeypatch.setenv("SMV2_IMPORT_MARKDOWN_EXPERIMENTAL", "1")
    course_id = _create_course(client)
    _upload_markdown(client, course_id, b"# Keep\n\nKeep body.\n\n# Change\n\nChange body.\n")
    _run_ingest(client, course_id)
    keep_id = _sections_by_title(course_id)["Keep"].id

    highlight = client.post(
        f"/api/courses/{course_id}/highlights",
        json={
            "section_id": keep_id,
            "exact": "SURVIVING-HIGHLIGHT-TOKEN",
            "note_md": "SURVIVING-HIGHLIGHT-NOTE",
        },
    )
    assert highlight.status_code == 201
    note = client.post(
        f"/api/courses/{course_id}/notes",
        json={
            "section_id": keep_id,
            "page": 1,
            "anchor_y": 0.25,
            "note_md": "SURVIVING-NOTE-TOKEN",
            "surface": "pdf",
        },
    )
    assert note.status_code == 201

    _replace_asset_bytes(course_id, b"# Keep\n\nKeep body.\n\n# Change\n\nChanged body.\n")
    _run_ingest(client, course_id)

    highlights = client.get(f"/api/courses/{course_id}/highlights").json()
    notes = client.get(f"/api/courses/{course_id}/notes").json()
    assert [item["id"] for item in highlights] == [highlight.json()["id"]]
    assert [item["id"] for item in notes] == [note.json()["id"]]

    highlight_search = client.get(
        f"/api/courses/{course_id}/search",
        params={"query": "SURVIVING-HIGHLIGHT-TOKEN", "document_type": "highlight"},
    )
    assert highlight_search.status_code == 200
    assert [item["doc_type"] for item in highlight_search.json()["items"]] == ["highlight"]

    note_search = client.get(
        f"/api/courses/{course_id}/search",
        params={"query": "SURVIVING-NOTE-TOKEN", "document_type": "note"},
    )
    assert note_search.status_code == 200
    assert [item["doc_type"] for item in note_search.json()["items"]] == ["note"]

    export = client.get(f"/api/courses/{course_id}/export")
    assert export.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export.content)) as zf:
        exported_highlights = json.loads(zf.read("highlights.json").decode("utf-8"))
        exported_notes = json.loads(zf.read("notes.json").decode("utf-8"))
    assert [item["id"] for item in exported_highlights["highlights"]] == [highlight.json()["id"]]
    assert [item["id"] for item in exported_notes["notes"]] == [note.json()["id"]]


def test_reingest_deletes_annotations_only_for_removed_sections(client, monkeypatch):
    """Catches deleting annotations whose owning section survived the diff."""
    monkeypatch.setenv("SMV2_IMPORT_MARKDOWN_EXPERIMENTAL", "1")
    course_id = _create_course(client)
    _upload_markdown(client, course_id, b"# Keep\n\nKeep body.\n\n# Remove\n\nRemove body.\n")
    _run_ingest(client, course_id)
    sections = _sections_by_title(course_id)

    keep_highlight = client.post(
        f"/api/courses/{course_id}/highlights",
        json={"section_id": sections["Keep"].id, "exact": "keep highlight"},
    )
    assert keep_highlight.status_code == 201
    removed_highlight = client.post(
        f"/api/courses/{course_id}/highlights",
        json={"section_id": sections["Remove"].id, "exact": "removed highlight"},
    )
    assert removed_highlight.status_code == 201
    keep_note = client.post(
        f"/api/courses/{course_id}/notes",
        json={
            "section_id": sections["Keep"].id,
            "page": 1,
            "anchor_y": 0.1,
            "note_md": "keep note",
            "surface": "pdf",
        },
    )
    assert keep_note.status_code == 201
    removed_note = client.post(
        f"/api/courses/{course_id}/notes",
        json={
            "section_id": sections["Remove"].id,
            "page": 1,
            "anchor_y": 0.2,
            "note_md": "removed note",
            "surface": "pdf",
        },
    )
    assert removed_note.status_code == 201

    _replace_asset_bytes(course_id, b"# Keep\n\nKeep body.\n")
    _run_ingest(client, course_id)

    session = get_session()
    try:
        assert session.get(Highlight, keep_highlight.json()["id"]) is not None
        assert session.get(Note, keep_note.json()["id"]) is not None
        assert session.get(Highlight, removed_highlight.json()["id"]) is None
        assert session.get(Note, removed_note.json()["id"]) is None
    finally:
        session.close()


def test_export_preserves_original_asset_markdown_and_source_provenance(client, monkeypatch):
    """Catches export dropping original bytes, exact body text, or locator metadata."""
    monkeypatch.setenv("SMV2_IMPORT_MARKDOWN_EXPERIMENTAL", "1")
    course_id = _create_course(client)
    original = b"# Exported Unit\n\nExact **Markdown** body.\n"
    asset_id = _upload_markdown(client, course_id, original, filename="original.md")
    _run_ingest(client, course_id)

    response = client.get(f"/api/courses/{course_id}/export")
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = zf.namelist()
        asset_name = next(name for name in names if name.startswith("assets/"))
        section_name = next(
            name
            for name in names
            if name.endswith("-exported-unit.md") and not name.startswith("assets/")
        )
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert zf.read(asset_name) == original
        assert zf.read(section_name).decode("utf-8") == "# Exported Unit\n\nExact **Markdown** body."

    section_entry = manifest["sections"][0]
    assert section_entry["source_format"] == "markdown"
    assert section_entry["source_locator"] == {
        "type": "heading",
        "asset_id": asset_id,
        "heading_path": ["Exported Unit"],
    }
    assert section_entry["source_label"] == "Exported Unit"


def test_malformed_asset_failure_does_not_delete_good_asset_sections(client, monkeypatch):
    """Catches a single extraction failure rolling back unrelated durable rows."""
    monkeypatch.setenv("SMV2_IMPORT_TEXT_EXPERIMENTAL", "1")
    monkeypatch.setenv("SMV2_IMPORT_MARKDOWN_EXPERIMENTAL", "1")
    course_id = _create_course(client)
    good = client.post(
        f"/api/courses/{course_id}/assets",
        files={"file": ("good.txt", b"Good text survives.", "text/plain")},
    )
    assert good.status_code == 201

    bad_bytes = b"\xff\xfe\x00\x00not valid utf-8"
    bad_path = data_dir() / "assets" / course_id / "bad.md"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_bytes(bad_bytes)
    session = get_session()
    try:
        bad = Asset(
            course_id=course_id,
            filename="bad.md",
            content_type="text/markdown",
            source_format="markdown",
            media_type="text/markdown",
            size_bytes=len(bad_bytes),
            sha256=hashlib.sha256(bad_bytes).hexdigest(),
            stored_path=str(bad_path),
            status="stored",
        )
        session.add(bad)
        session.commit()
        bad_id = bad.id
    finally:
        session.close()

    _run_ingest(client, course_id)

    session = get_session()
    try:
        good_asset = session.get(Asset, good.json()["id"])
        bad_asset = session.get(Asset, bad_id)
        sections = session.query(Section).filter(Section.course_id == course_id).all()
        assert good_asset.status == "extracted"
        assert bad_asset.status == "extract_failed"
        assert [section.body_md for section in sections] == ["Good text survives."]
    finally:
        session.close()
