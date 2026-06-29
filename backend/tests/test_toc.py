"""Tests for PDF table-of-contents extraction and TOC-first outline."""
from __future__ import annotations

import fitz

from SourceMind.backend.extract.pdf import extract_toc
from SourceMind.backend.pipeline.outline import sections_from_toc


def _pdf_with_toc(path, toc, n_pages):
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Page {i} content about topic {i}.")
    doc.set_toc(toc)  # [[level, title, page(1-based)], ...]
    doc.save(str(path))
    doc.close()


def test_extract_toc_reads_bookmarks(tmp_path):
    pdf = tmp_path / "book.pdf"
    _pdf_with_toc(pdf, [[1, "Chapter 1", 1], [1, "Chapter 2", 3], [2, "2.1 Sub", 4]], 6)
    toc = extract_toc(pdf)
    assert toc[0] == (1, "Chapter 1", 0)   # 1-based page 1 -> 0-based 0
    assert toc[1] == (1, "Chapter 2", 2)
    assert toc[2] == (2, "2.1 Sub", 3)


def test_extract_toc_empty_when_no_bookmarks(tmp_path):
    pdf = tmp_path / "plain.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf))
    doc.close()
    assert extract_toc(pdf) == []


def test_sections_from_toc_top_level_with_ranges():
    toc = [(1, "Integers", 0), (2, "1.1 x", 1), (1, "Fractions", 3), (1, "Decimals", 5)]
    secs = sections_from_toc(toc, total_pages=8)
    # Only the shallowest level (chapters) become sections; sub-section dropped.
    assert [s.title for s in secs] == ["Integers", "Fractions", "Decimals"]
    assert (secs[0].page_start, secs[0].page_end) == (0, 2)   # up to next chapter
    assert (secs[1].page_start, secs[1].page_end) == (3, 4)
    assert (secs[2].page_start, secs[2].page_end) == (5, 7)   # last -> end of doc
    assert len({s.section_id for s in secs}) == 3


def test_sections_from_toc_empty_inputs():
    assert sections_from_toc([], 5) == []
    assert sections_from_toc([(1, "   ", 0)], 5) == []


def test_ingest_prefers_toc_over_llm_outline(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{tmp_path / 't.db'}")
    monkeypatch.setenv("SOURCEMIND_ASSETS_DIR", str(tmp_path / "assets"))
    from SourceMind.backend.db import base, models
    from SourceMind.backend.pipeline import service

    base.init_db()
    pdf = tmp_path / "book.pdf"
    _pdf_with_toc(pdf, [[1, "Alpha", 1], [1, "Beta", 3]], 4)

    class PlanStub:
        """Returns plan metadata only — never an outline (TOC supplies that)."""
        def complete(self, prompt, *, system="", schema=None, max_tokens=4096):
            if schema and "items" in str(schema):
                return {"items": [
                    {"section_id": "toc0", "objectives": ["o"], "importance": "core", "prerequisites": []},
                    {"section_id": "toc1", "objectives": ["o"], "importance": "supporting", "prerequisites": []},
                ]}
            # If detect_outline were (wrongly) called, it'd get no sections.
            return {"sections": []}

    try:
        service.ingest_pdfs("bk", "Book", [pdf], provider=PlanStub())
        with base.get_session() as s:
            plans = (
                s.query(models.PlanItem)
                .filter_by(course_id="bk")
                .order_by(models.PlanItem.order)
                .all()
            )
            ids = [p.section_id for p in plans]
            course_title = s.get(models.Course, "bk").title
        # toc0/toc1 ids prove the outline came from the TOC, not the LLM.
        assert ids == ["toc0", "toc1"]
        # The course title must be the supplied one, NOT a TOC bookmark title
        # (guards against the TOC loop variable shadowing the title param).
        assert course_title == "Book"
    finally:
        base.reset_engine_cache()
