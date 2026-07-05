from __future__ import annotations

from app.pipeline.chunking import chunk_pages


def test_chunk_pages_splits_at_paragraph_boundaries_near_target():
    para = "x" * 800
    pages = [(0, f"{para}\n\n{para}\n\n{para}")]
    chunks = chunk_pages(pages, target_chars=1400)
    # Three 800-char paragraphs: first chunk holds paragraph 1 (800 <= 1400),
    # adding paragraph 2 would exceed 1400, so it flushes and starts fresh.
    assert len(chunks) == 3
    assert all(chunk.text == para for chunk in chunks)


def test_chunk_pages_attributes_chunk_to_its_first_paragraphs_page():
    pages = [(0, "short page zero text"), (1, "short page one text")]
    chunks = chunk_pages(pages, target_chars=1400)
    assert len(chunks) == 1
    assert chunks[0].page == 0
    assert "page zero" in chunks[0].text and "page one" in chunks[0].text


def test_chunk_pages_never_splits_a_single_oversized_paragraph():
    huge_para = "y" * 5000
    chunks = chunk_pages([(0, huge_para)], target_chars=1400)
    assert len(chunks) == 1
    assert chunks[0].text == huge_para


def test_chunk_pages_empty_input_produces_no_chunks():
    assert chunk_pages([]) == []
    assert chunk_pages([(0, "")]) == []
    assert chunk_pages([(0, "   \n\n  ")]) == []


def test_chunk_pages_preserves_paragraph_order():
    pages = [(0, "first paragraph"), (1, "second paragraph"), (2, "third paragraph")]
    chunks = chunk_pages(pages, target_chars=1400)
    assert len(chunks) == 1
    lines = chunks[0].text.split("\n\n")
    assert lines == ["first paragraph", "second paragraph", "third paragraph"]
