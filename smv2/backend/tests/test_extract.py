from __future__ import annotations

from pathlib import Path

import pytest

from app.pipeline.extract import PdfExtractionError, extract_markdown_pages, get_toc, open_pdf

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "pdfs"


def test_open_pdf_reads_page_count_and_toc():
    doc = open_pdf(FIXTURES_DIR / "with_bookmarks.pdf")
    try:
        assert doc.page_count == 12
        toc = get_toc(doc)
        assert len(toc) == 3
        assert [title for _, title, _ in toc] == [
            "Chapter 1: Foundations",
            "Chapter 2: Structures",
            "Chapter 3: Applications",
        ]
        assert all(level == 1 for level, _, _ in toc)
        assert [page for _, _, page in toc] == [0, 4, 8]
    finally:
        doc.close()


def test_get_toc_empty_for_no_bookmarks_pdf():
    doc = open_pdf(FIXTURES_DIR / "no_bookmarks.pdf")
    try:
        assert get_toc(doc) == []
    finally:
        doc.close()


def test_extract_markdown_pages_returns_one_entry_per_page():
    doc = open_pdf(FIXTURES_DIR / "with_bookmarks.pdf")
    try:
        pages = extract_markdown_pages(doc)
        assert len(pages) == doc.page_count == 12
        assert "Chapter 1: Foundations" in pages[0]
    finally:
        doc.close()


def test_open_pdf_raises_for_encrypted_pdf():
    with pytest.raises(PdfExtractionError, match="password-protected"):
        open_pdf(FIXTURES_DIR / "encrypted.pdf")


def test_open_pdf_raises_for_malformed_pdf():
    with pytest.raises(PdfExtractionError):
        open_pdf(FIXTURES_DIR / "malformed.pdf")


def test_extract_markdown_pages_handles_scanned_pdf_without_crashing():
    doc = open_pdf(FIXTURES_DIR / "scanned.pdf")
    try:
        pages = extract_markdown_pages(doc)
        assert len(pages) == doc.page_count
        # Drawn shapes only, no real text — sparse/empty is expected.
        assert all(len(p.strip()) == 0 for p in pages)
    finally:
        doc.close()


def test_extract_markdown_pages_preserves_unicode():
    doc = open_pdf(FIXTURES_DIR / "non_english.pdf")
    try:
        pages = extract_markdown_pages(doc)
        joined = "\n".join(pages)
        assert "Κεφάλαιο" in joined
        assert "Глава" in joined
        assert "кириллице" in joined
    finally:
        doc.close()


def test_extract_markdown_pages_covers_all_520_huge_pages():
    doc = open_pdf(FIXTURES_DIR / "huge.pdf")
    try:
        assert doc.page_count == 520
        pages = extract_markdown_pages(doc)
        assert len(pages) == 520
        assert "Tiny page 1" in pages[0]
        assert "Tiny page 520" in pages[519]
    finally:
        doc.close()
