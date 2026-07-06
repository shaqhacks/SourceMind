from __future__ import annotations

from pathlib import Path

import pytest

from app.pipeline.extract import (
    PdfExtractionError,
    extract_heading_candidates,
    extract_markdown_pages,
    extract_markdown_pages_in_batches,
    get_toc,
    open_pdf,
)

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


def test_extract_markdown_pages_in_batches_matches_single_call_output():
    """Batching by page subset must never change extracted text — pymupdf4llm's
    header/font-size classification always scans the whole document
    regardless of the `pages=` filter, independent of batch boundaries.
    """
    doc = open_pdf(FIXTURES_DIR / "with_bookmarks.pdf")
    try:
        whole = extract_markdown_pages(doc)
        batched = extract_markdown_pages_in_batches(doc, batch_pages=4)
        assert batched == whole
    finally:
        doc.close()


def test_extract_markdown_pages_in_batches_calls_on_batch_incrementally():
    doc = open_pdf(FIXTURES_DIR / "with_bookmarks.pdf")
    try:
        seen: list[tuple[int, int]] = []
        extract_markdown_pages_in_batches(doc, batch_pages=4, on_batch=lambda done, total: seen.append((done, total)))
        assert seen == [(4, 12), (8, 12), (12, 12)]
    finally:
        doc.close()


def test_extract_markdown_pages_in_batches_empty_for_zero_pages():
    class _EmptyDoc:
        page_count = 0

    assert extract_markdown_pages_in_batches(_EmptyDoc(), batch_pages=10) == []


def test_extract_heading_candidates_reports_size_and_bold_per_line():
    doc = open_pdf(FIXTURES_DIR / "headings_no_bookmarks.pdf")
    try:
        candidates = extract_heading_candidates(doc)
    finally:
        doc.close()

    by_text = {text.strip(): (page, size, bold) for page, text, size, bold in candidates}
    assert by_text["Chapter 1: Foundations"] == (0, 20.0, True)
    assert by_text["Chapter 4: Practice"] == (8, 20.0, True)
    # Ordinary body text is neither bold nor large.
    non_heading = next(
        (page, text, size, bold)
        for page, text, size, bold in candidates
        if page == 1 and "Foundations continue" in text
    )
    assert non_heading[2] == 11.0
    assert non_heading[3] is False


def test_extract_heading_candidates_empty_for_scanned_pdf():
    doc = open_pdf(FIXTURES_DIR / "scanned.pdf")
    try:
        assert extract_heading_candidates(doc) == []
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
