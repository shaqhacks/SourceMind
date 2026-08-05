from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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

