"""Tests for PDF table-of-contents extraction and TOC-first outline."""
from __future__ import annotations

import fitz

from SourceMind.backend.extract.pdf import ExtractedPage, extract_toc
from SourceMind.backend.pipeline.outline import (
    Section,
    carve_front_matter,
    detect_front_matter_pages,
    sections_from_page_windows,
    sections_from_toc,
)


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


def test_sections_from_toc_picks_deepest_qualifying_level():
    """A "Part" level with only 2 entries sitting above a 5-entry "Chapter"
    level must not win just because it's shallower — the deepest level whose
    count falls in [4, 80] is picked (see outline._pick_toc_level / ADR-010)."""
    toc = [
        (1, "Part I", 0), (1, "Part II", 5),
        (2, "Ch 1", 0), (2, "Ch 2", 1), (2, "Ch 3", 2), (2, "Ch 4", 3), (2, "Ch 5", 5),
    ]
    secs = sections_from_toc(toc, total_pages=10)
    assert [s.title for s in secs] == ["Ch 1", "Ch 2", "Ch 3", "Ch 4", "Ch 5"]


def test_sections_from_toc_falls_back_to_shallowest_when_no_level_qualifies():
    """Neither level has a count in [4, 80] -> falls back to the shallowest
    level (today's best-effort default) rather than erroring."""
    toc = [(1, "Alpha", 0), (1, "Beta", 2), (2, "Sub", 1)]
    secs = sections_from_toc(toc, total_pages=4)
    assert [s.title for s in secs] == ["Alpha", "Beta"]


def test_sections_from_page_windows_covers_whole_document():
    secs = sections_from_page_windows(34, pages_per_chapter=15)
    assert [(s.page_start, s.page_end) for s in secs] == [(0, 14), (15, 29), (30, 33)]
    assert [s.title for s in secs] == ["Pages 1–15", "Pages 16–30", "Pages 31–34"]
    assert [s.section_id for s in secs] == ["pages0", "pages15", "pages30"]


def test_sections_from_page_windows_empty_and_clamped_size():
    assert sections_from_page_windows(0, 15) == []
    # A non-positive window size is clamped to 1 rather than looping forever.
    secs = sections_from_page_windows(3, 0)
    assert len(secs) == 3


# ---------------------------------------------------------------------------
# detect_front_matter_pages / carve_front_matter — never fold title page,
# copyright, dedication, or a printed table of contents into "chapter 1"
# (regression for the real Beginning and Intermediate Algebra textbook, which
# has a title page + copyright/ISBN page + dedication page + 2 printed-TOC
# pages before its real Chapter 0 content — confirmed by hand against the
# actual PDF; ingesting it end-to-end now carves exactly those 5 pages off).
# ---------------------------------------------------------------------------


def _page(n: int, text: str) -> ExtractedPage:
    return ExtractedPage(page_number=n, text=text)


_REAL_CONTENT_PARAGRAPH = (
    "The ability to work comfortably with negative numbers is essential to "
    "success in algebra. For this reason we will do a quick review of adding, "
    "subtracting, multiplying, and dividing of integers before moving into "
    "more advanced material covered later in this chapter."
)


def test_detect_front_matter_pages_copyright_and_toc():
    pages = [
        _page(0, "ISBN #978-0-000-00000-0\nCopyright 2020, All Rights Reserved."),
        _page(1, "Table of Contents\nChapter 1: Intro .......................... 5\nChapter 2: More .......................... 12"),
        _page(2, _REAL_CONTENT_PARAGRAPH),
    ]
    assert detect_front_matter_pages(pages) == 2


def test_detect_front_matter_pages_dedication_page_not_a_gap():
    """A dedication/acknowledgments page between the title page and the TOC
    doesn't match the copyright/TOC-line signals directly but must still be
    swept in — the "thanks to"/"acknowledg" keywords catch it (real book:
    the dedication page sits between the copyright page and the printed TOC)."""
    pages = [
        _page(0, "Copyright 2020, All Rights Reserved."),
        _page(1, "Special thanks to my family for their support during this project."),
        _page(2, "Table of Contents\nCh 1 .......................... 5"),
        _page(3, _REAL_CONTENT_PARAGRAPH),
    ]
    assert detect_front_matter_pages(pages) == 3


def test_detect_front_matter_pages_none_when_first_page_is_content():
    assert detect_front_matter_pages([_page(0, _REAL_CONTENT_PARAGRAPH)]) == 0


def test_detect_front_matter_pages_bare_title_page_is_a_known_miss():
    """Documents a deliberate limitation: a bare title page with no
    boilerplate keyword at all (no "Copyright"/ISBN/byline pattern) is NOT
    detected — there's no low-word-count/sparse-page fallback, because real
    textbook pages are routinely just as short (an image-heavy chapter-
    opening page, a worked-example page that's mostly a diagram) and a false
    positive there would swallow real chapter content into "Front Matter".
    Harmless miss: the bare title page just stays part of "chapter 1", same
    as before front-matter carving existed."""
    pages = [_page(0, "My Textbook\nby Some Author"), _page(1, _REAL_CONTENT_PARAGRAPH)]
    assert detect_front_matter_pages(pages) == 0


def test_detect_front_matter_pages_empty_input():
    assert detect_front_matter_pages([]) == 0


def test_detect_front_matter_pages_capped():
    """A run of matching pages longer than the cap doesn't scan forever."""
    pages = [_page(i, "Copyright notice, All Rights Reserved.") for i in range(50)]
    assert detect_front_matter_pages(pages) == 30


def test_carve_front_matter_clips_toc_derived_first_chapter():
    sections = [
        Section(section_id="toc0", title="Chapter 1: Real Numbers", page_start=6, page_end=27),
        Section(section_id="toc1", title="Chapter 2: Equations", page_start=28, page_end=50),
    ]
    result = carve_front_matter(sections, front_matter_pages=6)
    assert [s.section_id for s in result] == ["front_matter", "toc0", "toc1"]
    assert result[0].title == "Front Matter"
    assert (result[0].page_start, result[0].page_end) == (0, 5)
    # Real bookmark title is untouched by clipping.
    assert result[1].title == "Chapter 1: Real Numbers"
    assert (result[1].page_start, result[1].page_end) == (6, 27)


def test_carve_front_matter_regenerates_page_window_placeholder_title():
    sections = sections_from_page_windows(total_pages=45, pages_per_chapter=15)
    result = carve_front_matter(sections, front_matter_pages=6)
    assert [s.section_id for s in result] == ["front_matter", "pages0", "pages15", "pages30"]
    assert result[1].title == "Pages 7–15"  # was "Pages 1–15"; clipped to start at page 6
    assert (result[1].page_start, result[1].page_end) == (6, 14)
    assert result[2].title == "Pages 16–30"  # untouched — starts after front matter already


def test_carve_front_matter_drops_first_section_wholly_inside_front_matter():
    """A page-window small enough that the ENTIRE first window is front
    matter: the window is dropped rather than emitted as an empty/negative range."""
    sections = sections_from_page_windows(total_pages=20, pages_per_chapter=3)  # first window: pages 0-2
    result = carve_front_matter(sections, front_matter_pages=6)  # front matter covers pages 0-5
    assert result[0].section_id == "front_matter"
    assert (result[0].page_start, result[0].page_end) == (0, 5)
    # "pages0" (0-2) and "pages3" (3-5) were wholly inside the front matter and are gone;
    # "pages6" (6-8) is the first section not fully covered by front matter.
    assert result[1].section_id == "pages6"


def test_carve_front_matter_noop_when_no_front_matter_detected():
    sections = [Section(section_id="toc0", title="Chapter 1", page_start=0, page_end=10)]
    assert carve_front_matter(sections, front_matter_pages=0) == sections


def test_carve_front_matter_still_injects_when_gap_precedes_first_section():
    """front_matter_pages always materializes the Front Matter section when
    positive — even if the first section starts well past it (a gap in
    between is unrelated pre-existing behavior, not something this function
    is responsible for closing)."""
    sections = [Section(section_id="toc0", title="Chapter 1", page_start=10, page_end=20)]
    result = carve_front_matter(sections, front_matter_pages=6)
    assert [s.section_id for s in result] == ["front_matter", "toc0"]
    assert (result[0].page_start, result[0].page_end) == (0, 5)
    assert result[1] == sections[0]  # untouched — no overlap to clip


def test_carve_front_matter_empty_sections():
    assert carve_front_matter([], front_matter_pages=6) == []


def test_ingest_prefers_toc_over_page_window_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{tmp_path / 't.db'}")
    monkeypatch.setenv("SOURCEMIND_ASSETS_DIR", str(tmp_path / "assets"))
    from SourceMind.backend.db import base, models
    from SourceMind.backend.pipeline import service

    base.init_db()
    pdf = tmp_path / "book.pdf"
    _pdf_with_toc(pdf, [[1, "Alpha", 1], [1, "Beta", 3]], 4)

    call_count = 0

    class CountingStub:
        """Ingest must be zero-LLM (ADR-010): this stub should never be called."""
        def complete(self, prompt, *, system="", schema=None, max_tokens=4096):
            nonlocal call_count
            call_count += 1
            return {"sections": [], "items": []}

    try:
        stub = CountingStub()
        service.ingest_pdfs("bk", "Book", [pdf], provider=stub)
        assert call_count == 0, "ingest must make zero LLM calls (ADR-010)"

        with base.get_session() as s:
            plans = (
                s.query(models.PlanItem)
                .filter_by(course_id="bk")
                .order_by(models.PlanItem.order)
                .all()
            )
            ids = [p.section_id for p in plans]
            course_title = s.get(models.Course, "bk").title
        # toc0/toc1 ids prove the outline came from the TOC, not a page window.
        assert ids == ["toc0", "toc1"]
        # The course title must be the supplied one, NOT a TOC bookmark title
        # (guards against the TOC loop variable shadowing the title param).
        assert course_title == "Book"
    finally:
        base.reset_engine_cache()
