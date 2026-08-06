from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

from app.db.engine import get_session
from app.db.identity import content_hash_for, normalize_text
from app.db.models import Asset, Course, Job, Section
from app.jobs.worker import run_due_jobs_once
from app.pipeline.import_adapters import NormalizedSection, NormalizedSourceDocument
from app.pipeline.source_locators import HeadingLocator

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pdfs"


def test_pdf_adapter_sniffs_by_file_content_not_filename_or_header():
    """Catches routing adapters by user-controlled filename/content-type
    instead of authoritative magic-byte sniffing.
    """
    from app.pipeline.import_adapters import PdfDocumentAdapter, choose_document_adapter

    pdf_path = FIXTURES_DIR / "with_bookmarks.pdf"
    asset = SimpleNamespace(
        id="asset-123",
        course_id="course-123",
        filename="renamed.bin",
        content_type="application/octet-stream",
        stored_path=str(pdf_path),
    )

    adapter = choose_document_adapter(asset, adapters=[PdfDocumentAdapter()])

    assert adapter.format_name == "pdf"


def test_pdf_adapter_keeps_section_text_and_page_ranges_stable():
    """Catches changing the existing PDF extraction/outline output while
    moving it behind the adapter boundary.
    """
    from app.pipeline.import_adapters import PdfDocumentAdapter

    pdf_path = FIXTURES_DIR / "with_bookmarks.pdf"
    asset = SimpleNamespace(
        id="asset-123",
        course_id="course-123",
        filename="with_bookmarks.pdf",
        content_type="application/pdf",
        stored_path=str(pdf_path),
    )

    document = PdfDocumentAdapter().extract(asset)

    assert document.source_format == "pdf"
    assert document.extractor_name == "pymupdf4llm"
    assert [section.title for section in document.sections] == [
        "Chapter 1: Foundations",
        "Chapter 2: Structures",
        "Chapter 3: Applications",
    ]
    assert [(section.page_start, section.page_end) for section in document.sections] == [
        (0, 3),
        (4, 7),
        (8, 11),
    ]
    assert "Chapter 1: Foundations" in document.sections[0].body_md
    assert document.sections[0].source_locator.to_dict() == {
        "type": "pdf_pages",
        "asset_id": "asset-123",
        "page_start": 1,
        "page_end": 4,
    }


class _FakeMarkdownAdapter:
    format_name = "markdown"
    format_version = "1"
    media_type = "text/markdown"

    def sniff(self, asset):
        return asset.filename.endswith(".md")

    def extract(self, asset):
        body_md = normalize_text("# Module 1\n\nMarkdown adapter body.")
        return NormalizedSourceDocument(
            metadata={"page_count": None, "total_chars": len(body_md)},
            sections=[
                NormalizedSection(
                    stable_section_id=None,
                    title="Module 1",
                    body_md=body_md,
                    content_hash=content_hash_for(body_md),
                    source_locator=HeadingLocator(
                        asset_id=asset.id,
                        heading_path=["Module 1"],
                    ),
                    chapter_label=None,
                    asset_id=asset.id,
                    source_format="markdown",
                    page_start=None,
                    page_end=None,
                    kind="content",
                    pages=[],
                )
            ],
            warnings=[],
            failures=[],
            extractor_name="fake-markdown",
            extractor_version="fake-markdown-v1",
            source_format="markdown",
        )


def test_ingest_persists_non_pdf_document_identity_without_pdf_provenance(client, tmp_path, monkeypatch):
    """Catches ingest stamping every normalized document with the global PDF
    extractor identity or requiring PDF page provenance for future adapters.
    """
    from app.config import data_dir
    from app.pipeline import ingest as ingest_pipeline

    course_resp = client.post("/api/courses", json={"title": "Markdown Course"})
    assert course_resp.status_code == 201
    course_id = course_resp.json()["id"]
    asset_id = "asset-md"
    stored_path = data_dir() / "assets" / course_id / "asset-md.md"
    stored_path.parent.mkdir(parents=True, exist_ok=True)
    stored_path.write_text("# Module 1\n\nMarkdown adapter body.", encoding="utf-8")

    session = get_session()
    try:
        asset = Asset(
            id=asset_id,
            course_id=course_id,
            filename="module.md",
            content_type="text/markdown",
            source_format="unknown",
            media_type="application/octet-stream",
            size_bytes=stored_path.stat().st_size,
            sha256="b" * 64,
            stored_path=str(stored_path),
            status="stored",
        )
        session.add(asset)
        session.add(Job(type="ingest", status="queued", payload={"course_id": course_id}))
        session.commit()
    finally:
        session.close()

    def _fake_adapter_for_asset(asset, *, on_batch=None):
        return _FakeMarkdownAdapter()

    monkeypatch.setattr(ingest_pipeline, "_document_adapter_for_asset", _fake_adapter_for_asset)

    assert run_due_jobs_once() is True

    session = get_session()
    try:
        course = session.get(Course, course_id)
        asset = session.get(Asset, asset_id)
        section = session.query(Section).filter(Section.course_id == course_id).one()
        assert course.status == "ready"
        assert asset.source_format == "markdown"
        assert asset.media_type == "text/markdown"
        assert section.source_format == "markdown"
        assert section.extractor_version == "fake-markdown-v1"
        assert section.page_start is None
        assert section.page_end is None
        assert section.source_locator == {
            "type": "heading",
            "asset_id": asset_id,
            "heading_path": ["Module 1"],
        }
    finally:
        session.close()

    sections = client.get(f"/api/courses/{course_id}/sections").json()
    assert sections[0]["source_format"] == "markdown"
    assert sections[0]["page_start"] is None
    assert sections[0]["page_end"] is None
    assert sections[0]["source_locator"] == {
        "type": "heading",
        "asset_id": asset_id,
        "heading_path": ["Module 1"],
    }

    export_resp = client.get(f"/api/courses/{course_id}/export")
    assert export_resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(export_resp.content)) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
    assert manifest["sections"][0]["source_format"] == "markdown"
    assert manifest["sections"][0]["extractor_version"] == "fake-markdown-v1"
    assert manifest["sections"][0]["source_locator"]["type"] == "heading"
    assert manifest["sections"][0]["source_label"] == "Module 1"
