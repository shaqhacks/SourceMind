"""TDD tests for backend.pipeline.service — Task 10 orchestration layer."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import fitz  # PyMuPDF
import pytest

from SourceMind.backend.db import base, models
from SourceMind.backend.extract.pdf import ExtractedPage
from SourceMind.backend.pipeline.service import (
    approve_plan,
    ensure_plan_metadata,
    ensure_study,
    generate_course,
    generate_lesson,
    get_image_urls,
    get_source_text,
    ingest_pdfs,
    maybe_refine_title,
    reconcile_interrupted_jobs,
    regenerate_section,
    run_title_refinement_job,
)

# ---------------------------------------------------------------------------
# Chapter body that parse_quiz / parse_cards will successfully parse
# ---------------------------------------------------------------------------

GOOD_CHAPTER_MD = """
> *This topic is fundamental to understanding the rest of the material.*

By the end of this section you can:
- Understand the core concept
- Apply it in practice

## Core Concepts

This is the main explanation of the topic covering fundamental ideas.
It builds understanding from the ground up with rich detailed content.
Each idea connects to the next in a pedagogically sound sequence.
The material here gives the reader a solid foundation to proceed.

## Advanced Applications

Building on the fundamentals we explore real-world applications.
The following examples demonstrate practical use of the concepts.

### Worked Example 1: Basic Application

**Problem**: Show how to apply the core concept simply.

**Step 1**: Identify the inputs and expected outputs.

**Step 2**: Apply the transformation according to the rules.

**Step 3**: Verify the output against known expectations.

The result is consistent with what the theory predicts.

### Worked Example 2: Advanced Application

**Problem**: Demonstrate a more complex multi-step scenario.

**Step 1**: Decompose the problem into sub-problems.

**Step 2**: Solve each sub-problem using the core technique.

**Step 3**: Combine the partial results into the final answer.

## \U0001f4dd Section Check

```quiz
[
  {"q": "Q1", "options": ["A","B","C","D"], "answer": 0, "explain": "A is correct."},
  {"q": "Q2", "options": ["A","B","C","D"], "answer": 1, "explain": "B is correct."},
  {"q": "Q3", "options": ["A","B","C","D"], "answer": 2, "explain": "C is correct."},
  {"q": "Q4", "options": ["A","B","C","D"], "answer": 3, "explain": "D is correct."}
]
```

## Spaced-Repetition Cards

- **Q:** What is the key concept? **A:** The fundamental idea.
- **Q:** How do you apply it? **A:** By following the steps.
"""


# ---------------------------------------------------------------------------
# Stub LLM Provider
# ---------------------------------------------------------------------------

class StubProvider:
    """Deterministic LLM stub that returns canned responses based on schema keys."""

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        schema: dict | None = None,
        max_tokens: int = 4096,
    ) -> str | dict:
        if schema is not None:
            if "sections" in schema.get("properties", {}):
                return {
                    "sections": [
                        {
                            "section_id": "s1",
                            "title": "Algebra Basics",
                            "page_start": 0,
                            "page_end": 1,
                        },
                        {
                            "section_id": "s2",
                            "title": "Advanced Topics",
                            "page_start": 2,
                            "page_end": 3,
                        },
                    ]
                }
            if "items" in schema.get("properties", {}):
                return {
                    "items": [
                        {
                            "section_id": "s1",
                            "objectives": ["Learn basics"],
                            "importance": "core",
                            "prerequisites": [],
                        },
                        {
                            "section_id": "s2",
                            "objectives": ["Apply concepts"],
                            "importance": "supporting",
                            "prerequisites": ["s1"],
                        },
                    ]
                }
            if "grounded" in schema.get("properties", {}):
                return {"grounded": True, "unsupported": []}
            if "quiz" in schema.get("properties", {}):
                # generate_study_items schema → fixed quiz + cards
                return {
                    "quiz": [
                        {
                            "q": "What is 2 + 2?",
                            "options": ["3", "4", "5", "6"],
                            "answer": "4",
                            "explain": "Basic arithmetic.",
                        },
                    ],
                    "cards": [
                        {"q": "What is a variable?", "a": "A named placeholder for a value."},
                        {"q": "What is a constant?", "a": "A fixed value that does not change."},
                    ],
                }
            # Fallback for any schema
            return {}
        # No schema — chapter generation or repair
        return GOOD_CHAPTER_MD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_url(tmp_path, monkeypatch):
    """Monkeypatch DB URL to a temporary SQLite file and initialise tables."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{db_path}")
    # Point assets / pages.json to tmp_path so nothing lands in data/
    monkeypatch.setenv("SOURCEMIND_ASSETS_DIR", str(tmp_path / "data"))
    base.init_db()
    yield
    base.reset_engine_cache()


def _build_four_page_pdf(tmp_path: Path) -> Path:
    """Create a 4-page PDF with distinct text on each page using PyMuPDF."""
    pdf_path = tmp_path / "test_course.pdf"
    doc = fitz.open()
    for i in range(4):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), f"page-{i} content algebra topic section")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def _build_one_page_pdf_with_image(
    pdf_path: Path, color: tuple[int, int, int]
) -> Path:
    """Create a 1-page PDF with text and a single distinctly-coloured image.

    Mirrors backend/tests/test_extract_pdf.py: a tiny 10x10 RGB Pixmap is
    inserted via ``page.insert_image`` so ``extract_pdf`` saves it under
    ``page0_img{xref}.png`` in the assets directory it is given.
    """
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "page-0 content algebra topic section")

    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
    pix.set_rect(fitz.IRect(0, 0, 10, 10), color)
    page.insert_image(fitz.Rect(100, 100, 150, 150), pixmap=pix)

    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_ingest_creates_course_and_plan(tmp_path, db_url):
    stub = StubProvider()
    pdf_path = _build_four_page_pdf(tmp_path)

    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)

    with base.get_session() as session:
        course = session.get(models.Course, "algebra")
        assert course is not None
        assert course.id == "algebra"
        # New lazy-ingest flow: course is immediately "ready" (no approve/generate gate)
        assert course.status == "ready"
        assert course.generation_status == "idle"

        plan_items = (
            session.query(models.PlanItem).filter_by(course_id="algebra").all()
        )
        assert len(plan_items) >= 1

        chapters = (
            session.query(models.Chapter).filter_by(course_id="algebra").all()
        )
        assert len(chapters) >= 1
        # Chapters are created "ready" with their real source text in body_md
        assert all(ch.status == "ready" for ch in chapters)
        assert all(ch.body_md for ch in chapters)
        assert all(ch.lesson_status == "none" for ch in chapters)
        assert all(ch.source_pages is not None for ch in chapters)


def test_approve_plan_sets_status(tmp_path, db_url):
    stub = StubProvider()
    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)

    approve_plan("algebra")

    with base.get_session() as session:
        course = session.get(models.Course, "algebra")
        assert course.status == "generating"


def test_generate_course_full_flow(tmp_path, db_url):
    stub = StubProvider()
    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)
    approve_plan("algebra")

    generate_course("algebra", provider=stub)

    with base.get_session() as session:
        course = session.get(models.Course, "algebra")
        assert course.status == "ready"

        chapters = (
            session.query(models.Chapter).filter_by(course_id="algebra").all()
        )
        assert all(ch.status == "ready" for ch in chapters)
        assert all(ch.body_md for ch in chapters)

        progress = course.generation_progress
        assert progress is not None
        assert progress["completed"] == progress["total"]
        assert progress["failed"] == 0
        assert course.generation_status == "succeeded"


def test_generate_course_persists_quiz_and_cards(tmp_path, db_url):
    stub = StubProvider()
    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)
    approve_plan("algebra")
    generate_course("algebra", provider=stub)

    with base.get_session() as session:
        chapters = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", status="ready")
            .all()
        )
        assert len(chapters) >= 1
        for ch in chapters:
            assert ch.quiz is not None and len(ch.quiz) > 0
            assert ch.cards is not None and len(ch.cards) > 0
            # generate_course now produces the verbose lesson into lesson_md
            assert ch.lesson_status == "ready"
            assert ch.lesson_md


def test_regenerate_section(tmp_path, db_url):
    """regenerate_section leaves body_md (source) intact and updates lesson_md/lesson_status.

    Prior to the fix, regenerate_section wrote the LLM draft into body_md
    (clobbering the extracted source text) and never touched lesson_md, so a
    chapter generated via generate_course/generate_lesson and then
    regenerated would silently diverge back to showing stale lesson content.
    """
    stub = StubProvider()
    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)
    approve_plan("algebra")
    generate_course("algebra", provider=stub)

    # 4 pages, no bookmarks, default 15-page fallback window -> single
    # deterministic section "pages0" (see sections_from_page_windows / ADR-010).
    with base.get_session() as session:
        ch = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert ch is not None
        original_body_md = ch.body_md
        assert original_body_md  # real source text, populated at ingest
        # Simulate a stale/failed lesson that needs regeneration.
        ch.lesson_md = "STALE LESSON CONTENT"
        ch.lesson_status = "failed"

    regenerate_section("algebra", "pages0", provider=stub)

    with base.get_session() as session:
        ch = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert ch is not None
        assert ch.body_md == original_body_md, "source text must not be touched by regeneration"
        assert ch.lesson_status == "ready"
        assert ch.lesson_md and ch.lesson_md != "STALE LESSON CONTENT"


def test_source_text_helper():
    pages = [
        ExtractedPage(page_number=0, text="page-0"),
        ExtractedPage(page_number=1, text="page-1"),
        ExtractedPage(page_number=2, text="page-2"),
        ExtractedPage(page_number=3, text="page-3"),
    ]
    result = get_source_text(pages, 1, 2)
    assert "page-1" in result
    assert "page-2" in result
    assert "page-0" not in result
    assert "page-3" not in result


def test_image_urls_helper():
    """get_image_urls returns HTTP URL strings when course_id is supplied."""
    prefix = "/library/courses/algebra/assets/"

    # Attribute-style (ORM objects / SimpleNamespace) — paths not under the
    # real assets dir, so the basename fallback is used as the relpath.
    assets = [
        SimpleNamespace(path="img0.png", source_page=0),
        SimpleNamespace(path="img1.png", source_page=1),
        SimpleNamespace(path="img2.png", source_page=2),
        SimpleNamespace(path="img3.png", source_page=3),
    ]
    result = get_image_urls(assets, 1, 2, course_id="algebra")
    assert len(result) == 2
    assert all(r.startswith(prefix) for r in result)
    assert any(r.endswith("img1.png") for r in result)
    assert any(r.endswith("img2.png") for r in result)

    # Dict-style (mirrors the plain-dict asset_records used in generate_course)
    dict_assets = [
        {"path": "img0.png", "source_page": 0},
        {"path": "img1.png", "source_page": 1},
        {"path": "img2.png", "source_page": 2},
        {"path": "img3.png", "source_page": 3},
    ]
    dict_result = get_image_urls(dict_assets, 1, 2, course_id="algebra")
    assert len(dict_result) == 2
    assert all(r.startswith(prefix) for r in dict_result)
    assert any(r.endswith("img1.png") for r in dict_result)
    assert any(r.endswith("img2.png") for r in dict_result)


def test_get_image_urls_http_url_format(tmp_path, db_url):
    """get_image_urls returns /library/courses/{id}/assets/{relpath} for real asset paths."""
    from SourceMind.backend.pipeline.service import course_assets_dir

    course_id = "url_format_test"
    assets_dir = course_assets_dir(course_id)
    src_dir = assets_dir / "src0"
    src_dir.mkdir(parents=True, exist_ok=True)

    real_file = src_dir / "page0_img1.png"
    real_file.write_bytes(b"PNG")

    assets = [SimpleNamespace(path=str(real_file), source_page=0)]
    result = get_image_urls(assets, 0, 0, course_id=course_id)

    assert len(result) == 1
    url = result[0]
    assert url.startswith(f"/library/courses/{course_id}/assets/"), url
    assert url.endswith("src0/page0_img1.png"), url


def test_generate_course_isolates_section_failure(tmp_path, db_url, monkeypatch):
    """Verify that a single section failure does not abort generation of other sections.

    The first call to generate_validated raises; subsequent calls delegate to the
    real implementation via the StubProvider.  After generate_course completes:
    - exactly the first chapter is ``status="failed"``
    - the remaining chapter(s) are ``status="ready"``
    - Course.generation_last_error is set
    - generation_progress["failed"] >= 1 and completed+failed == total
    - Course.generation_status == "failed"
    """
    # Force >=2 page-window sections out of the 4-page PDF (default 15-page
    # window would produce a single "pages0" section, defeating this isolation
    # test — see sections_from_page_windows / ADR-010).
    monkeypatch.setenv("SOURCEMIND_FALLBACK_PAGES_PER_CHAPTER", "2")
    stub = StubProvider()
    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)
    approve_plan("algebra")

    # Import the real function so we can delegate non-failing calls to it.
    from SourceMind.backend.pipeline.validate import (
        generate_validated as _real_generate_validated,
    )

    call_count = 0

    def _failing_first(plan_dc, source_text, image_urls, provider, *, had_figures=False):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated section failure for isolation test")
        return _real_generate_validated(
            plan_dc, source_text, image_urls, provider, had_figures=had_figures
        )

    monkeypatch.setattr(
        "SourceMind.backend.pipeline.service.generate_validated",
        _failing_first,
    )

    generate_course("algebra", provider=stub)

    with base.get_session() as session:
        course = session.get(models.Course, "algebra")
        chapters = (
            session.query(models.Chapter).filter_by(course_id="algebra").all()
        )

        # Lazy flow tracks per-section success via lesson_status, not chapter.status
        # (chapters stay status="ready" since body_md/source text is always present).
        failed_chapters = [ch for ch in chapters if ch.lesson_status == "failed"]
        ready_chapters = [ch for ch in chapters if ch.lesson_status == "ready"]

        # At least one section failed and at least one continued to succeed
        assert len(failed_chapters) >= 1, "Expected at least one failed chapter"
        assert len(ready_chapters) >= 1, "Expected remaining sections to still succeed"

        # Error was recorded on the course
        assert course.generation_last_error, "generation_last_error should be non-empty"

        # Progress counters are consistent
        progress = course.generation_progress
        assert progress["failed"] >= 1
        assert progress["completed"] + progress["failed"] == progress["total"]

        # Overall course generation status reflects the partial failure
        assert course.generation_status == "failed"

        # The course's public status is "failed" when any section failed
        assert course.status == "failed"


def test_ingest_two_pdfs_with_images_no_collision(tmp_path, db_url):
    """Two PDFs each with a page-0 image must persist distinct, non-overwritten assets.

    ``extract_pdf`` names images by LOCAL page index (``page0_img{xref}.png``),
    so extracting two single-page PDFs into the SAME directory would overwrite
    the first PDF's image with the second's.  ``ingest_pdfs`` must isolate each
    source PDF into its own subdir so the Asset rows record distinct paths that
    all still exist on disk.
    """
    stub = StubProvider()
    pdf_a = _build_one_page_pdf_with_image(tmp_path / "a.pdf", (255, 0, 0))
    pdf_b = _build_one_page_pdf_with_image(tmp_path / "b.pdf", (0, 0, 255))

    ingest_pdfs("algebra", "Algebra", [pdf_a, pdf_b], provider=stub)

    with base.get_session() as session:
        assets = (
            session.query(models.Asset).filter_by(course_id="algebra").all()
        )
        paths = [a.path for a in assets]

    # At least one image per PDF was persisted
    assert len(paths) >= 2, f"Expected >=2 asset rows, got {len(paths)}: {paths}"

    # Paths are distinct (no collision / overwrite)
    assert len(set(paths)) == len(paths), f"Asset paths collided: {paths}"

    # Every recorded image still exists on disk (neither was overwritten)
    for p in paths:
        assert Path(p).exists(), f"Asset image missing on disk: {p}"


def test_regenerate_section_marks_failed_on_error(tmp_path, db_url, monkeypatch):
    """If regeneration raises, the chapter's lesson_status ends 'failed' and no exception escapes.

    regenerate_section now delegates to generate_lesson, which tracks
    generation outcome via lesson_status (not the source-availability
    ``status`` field, which is untouched by lesson generation/regeneration).
    """
    stub = StubProvider()
    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)
    approve_plan("algebra")
    generate_course("algebra", provider=stub)

    def _always_fail(plan_dc, source_text, image_urls, provider, *, had_figures=False):
        raise RuntimeError("Simulated regeneration failure")

    monkeypatch.setattr(
        "SourceMind.backend.pipeline.service.generate_validated",
        _always_fail,
    )

    # Must NOT raise — failure is recorded on the chapter/course instead.
    # 4 pages, no bookmarks -> single deterministic section "pages0" (ADR-010).
    regenerate_section("algebra", "pages0", provider=stub)

    with base.get_session() as session:
        ch = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert ch is not None
        assert ch.lesson_status == "failed"

        course = session.get(models.Course, "algebra")
        assert course.generation_last_error, "generation_last_error should be set"


# ---------------------------------------------------------------------------
# SRS seed tests (RED → GREEN after Fix 1 in service.py)
# ---------------------------------------------------------------------------

def test_generate_course_seeds_review_states(tmp_path, db_url):
    """After generate_course, ReviewState rows exist for all cards and are immediately due."""
    from SourceMind.backend.services import review

    stub = StubProvider()
    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)
    approve_plan("algebra")
    generate_course("algebra", provider=stub)

    with base.get_session() as session:
        chapters = (
            session.query(models.Chapter).filter_by(course_id="algebra").all()
        )
        total_cards = sum(len(ch.cards or []) for ch in chapters)
        assert total_cards > 0, "Expected at least one card after generation"

        due = review.due_cards(session, "algebra")
        assert len(due) == total_cards, (
            f"Expected {total_cards} due ReviewState rows, got {len(due)}"
        )

        # Spot-check: first chapter's cards have correct (section_id, card_index)
        chapter = chapters[0]
        section_rows = [r for r in due if r.section_id == chapter.section_id]
        assert len(section_rows) == len(chapter.cards or [])
        indices = {r.card_index for r in section_rows}
        assert indices == set(range(len(chapter.cards or [])))


def test_regenerate_section_does_not_duplicate_review_states(tmp_path, db_url):
    """Regenerating a section replaces (not duplicates) its ReviewState rows."""
    stub = StubProvider()
    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)
    approve_plan("algebra")
    generate_course("algebra", provider=stub)

    with base.get_session() as session:
        count_before = (
            session.query(models.ReviewState).filter_by(course_id="algebra").count()
        )
    assert count_before > 0

    # 4 pages, no bookmarks -> single deterministic section "pages0" (ADR-010).
    regenerate_section("algebra", "pages0", provider=stub)

    with base.get_session() as session:
        count_after = (
            session.query(models.ReviewState).filter_by(course_id="algebra").count()
        )
    assert count_after == count_before, (
        f"Regeneration duplicated ReviewState rows: before={count_before}, after={count_after}"
    )


def test_ingest_materials_txt(tmp_path, db_url, monkeypatch):
    """ingest_materials with a .txt material → Course persisted, Chapters created, pages.json written."""
    from SourceMind.backend.pipeline.service import ingest_materials, course_assets_dir

    # Stub embed_texts so no Ollama call is attempted; index_course failure is
    # swallowed by the try/except inside _finish_ingest, but stubbing keeps
    # test output clean.
    monkeypatch.setattr(
        "SourceMind.backend.pipeline.service.embed_texts",
        lambda texts: [[0.0] * 8 for _ in texts],
    )

    # Write a text file with enough words to produce 2+ pages (paginate_text
    # chunks at 500 words by default, so 600 words → 2 pages).
    content = ("word " * 600).strip()
    txt_file = tmp_path / "lecture.txt"
    txt_file.write_text(content)

    stub = StubProvider()
    ingest_materials(
        "algebra_txt",
        "Algebra TXT",
        [{"kind": "txt", "path": str(txt_file)}],
        provider=stub,
    )

    with base.get_session() as session:
        course = session.get(models.Course, "algebra_txt")
        assert course is not None
        assert course.status == "ready"
        chapters = session.query(models.Chapter).filter_by(course_id="algebra_txt").all()
        assert len(chapters) >= 1

    pages_file = (course_assets_dir("algebra_txt") / ".." / "pages.json").resolve()
    assert pages_file.exists()


def test_ingest_materials_mixed_pdf_txt_uses_page_window_fallback(tmp_path, db_url, monkeypatch):
    """Mixed PDF+TXT ingest clears toc_entries and falls back to page windows.

    Without the Finding-3 fix, sections_from_toc would absorb the appended TXT
    pages into the last PDF chapter, mis-attributing content. With the fix,
    toc_entries is emptied for mixed sets so the deterministic page-window
    fallback always runs instead (ADR-010: no LLM outline call exists anymore
    to fall back to — ingest is zero-LLM end to end).
    """
    from SourceMind.backend.pipeline.service import ingest_materials, course_assets_dir

    monkeypatch.setattr(
        "SourceMind.backend.pipeline.service.embed_texts",
        lambda texts: [[0.0] * 8 for _ in texts],
    )

    # Build a 2-page PDF with an embedded TOC.
    pdf_path = tmp_path / "toc_course.pdf"
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), f"PDF page {i} algebra content topic section")
    # set_toc takes [[level, title, page_number], ...] with 1-based page numbers.
    doc.set_toc([[1, "Chapter A", 1], [1, "Chapter B", 2]])
    doc.save(str(pdf_path))
    doc.close()

    # Add a TXT material — this makes the set mixed, triggering the fix.
    txt_file = tmp_path / "extra.txt"
    txt_file.write_text(("word " * 300).strip())

    call_count = 0

    class CountingStub(StubProvider):
        def complete(self, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            return super().complete(*args, **kwargs)

    ingest_materials(
        "mixed_course",
        "Mixed Course",
        [{"kind": "pdf", "path": str(pdf_path)}, {"kind": "txt", "path": str(txt_file)}],
        provider=CountingStub(),
    )

    assert call_count == 0, "ingest must make zero LLM calls (ADR-010)"

    with base.get_session() as session:
        course = session.get(models.Course, "mixed_course")
        assert course is not None
        assert course.status == "ready", (
            f"Expected ready; got {course.status!r}. "
            f"error: {course.generation_last_error!r}"
        )

        chapters = session.query(models.Chapter).filter_by(course_id="mixed_course").all()
        assert len(chapters) >= 1

        # 2 PDF pages + 1 TXT page = 3 total, under the 15-page default window
        # -> single deterministic section "pages0" covering the whole document.
        # Confirm the TOC path was suppressed (no "toc0"/"toc1" ids, which
        # would indicate the PDF's own 2-chapter bookmarks mis-absorbed the
        # appended TXT page into "Chapter B").
        section_ids = {ch.section_id for ch in chapters}
        assert section_ids == {"pages0"}, (
            f"Expected the page-window fallback (\"pages0\"); got section_ids={section_ids}. "
            "The TOC path should have been suppressed for mixed material sets."
        )
        chapter = chapters[0]
        assert chapter.title_status == "placeholder"
        assert chapter.title.startswith("Pages ")


def test_reingest_same_course_id_replaces_not_duplicates(tmp_path, db_url, monkeypatch):
    """Running _finish_ingest twice for the same course_id (via ingest_pdfs)
    yields exactly one set of PlanItem/Chapter/Asset rows, and clears any
    stale ReviewState/ProgressState/ChatTurn/TestAttempt rows left over from
    a prior generation (they may reference section_ids the new outline drops).
    """
    monkeypatch.setattr(
        "SourceMind.backend.pipeline.service.embed_texts",
        lambda texts: [[0.0] * 8 for _ in texts],
    )
    stub = StubProvider()
    pdf_path = _build_one_page_pdf_with_image(tmp_path / "course.pdf", (255, 0, 0))

    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)

    with base.get_session() as session:
        plan_count_1 = session.query(models.PlanItem).filter_by(course_id="algebra").count()
        chapter_count_1 = session.query(models.Chapter).filter_by(course_id="algebra").count()
        asset_count_1 = session.query(models.Asset).filter_by(course_id="algebra").count()
        assert plan_count_1 >= 1
        assert chapter_count_1 >= 1
        assert asset_count_1 >= 1

        # Simulate leftover rows from a prior generation/study/chat/test session,
        # all referencing a section_id that the re-ingested outline may no
        # longer produce.
        session.add(models.ReviewState(
            course_id="algebra",
            section_id="s1",
            card_index=0,
            ease=2.5,
            interval=0,
            due_at="",
            reps=0,
        ))
        session.add(models.ReviewLog(
            course_id="algebra",
            section_id="s1",
            card_index=0,
            quality=3,
            created_at="",
        ))
        session.add(models.ProgressState(
            course_id="algebra",
            section_id="s1",
            completed=True,
            last_viewed_at="",
        ))
        session.add(models.ChatTurn(
            course_id="algebra",
            section_id="s1",
            role="user",
            content="stale question",
            created_at="",
        ))
        session.add(models.TestAttempt(
            course_id="algebra",
            section_id="s1",
            scope="section",
            answers=[0],
            correct=1,
            total=1,
            score=1.0,
            passed=True,
            created_at="",
        ))

    # Re-ingest the SAME course_id (e.g. the user re-uploads the same file).
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)

    with base.get_session() as session:
        plan_count_2 = session.query(models.PlanItem).filter_by(course_id="algebra").count()
        chapter_count_2 = session.query(models.Chapter).filter_by(course_id="algebra").count()
        asset_count_2 = session.query(models.Asset).filter_by(course_id="algebra").count()
        review_count_2 = session.query(models.ReviewState).filter_by(course_id="algebra").count()
        review_log_count_2 = session.query(models.ReviewLog).filter_by(course_id="algebra").count()
        progress_count_2 = session.query(models.ProgressState).filter_by(course_id="algebra").count()
        chat_count_2 = session.query(models.ChatTurn).filter_by(course_id="algebra").count()
        attempt_count_2 = session.query(models.TestAttempt).filter_by(course_id="algebra").count()

    assert plan_count_2 == plan_count_1, "PlanItem rows duplicated on re-ingest"
    assert chapter_count_2 == chapter_count_1, "Chapter rows duplicated on re-ingest"
    assert asset_count_2 == asset_count_1, "Asset rows duplicated on re-ingest"
    assert review_count_2 == 0, "stale ReviewState rows must be cleared on re-ingest"
    assert review_log_count_2 == 0, "stale ReviewLog rows must be cleared on re-ingest"
    assert progress_count_2 == 0, "stale ProgressState rows must be cleared on re-ingest"
    assert chat_count_2 == 0, "stale ChatTurn rows must be cleared on re-ingest"
    assert attempt_count_2 == 0, "stale TestAttempt rows must be cleared on re-ingest"


# ---------------------------------------------------------------------------
# Lazy study + lesson generation (new lazy-ingest flow)
# ---------------------------------------------------------------------------


def test_ensure_study_generates_quiz_cards(tmp_path, db_url):
    """ensure_study fills quiz/cards from body_md, seeds ReviewState, and is idempotent."""
    stub = StubProvider()
    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)

    # 4 pages, no bookmarks -> single deterministic section "pages0" (ADR-010).
    # Sanity: chapter exists with source body_md but no quiz yet.
    with base.get_session() as session:
        chap = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert chap is not None
        assert chap.body_md  # real source text from ingest
        assert not chap.quiz

    ensure_study("algebra", "pages0", provider=stub)

    with base.get_session() as session:
        chap = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert chap.quiz is not None and len(chap.quiz) == 1
        assert chap.cards is not None and len(chap.cards) == 2

        review_count = (
            session.query(models.ReviewState)
            .filter_by(course_id="algebra", section_id="pages0")
            .count()
        )
        # One ReviewState row seeded per card.
        assert review_count == 2

    # Idempotent: a second call must not duplicate cards or ReviewState rows.
    ensure_study("algebra", "pages0", provider=stub)

    with base.get_session() as session:
        chap = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert len(chap.cards) == 2
        review_count_after = (
            session.query(models.ReviewState)
            .filter_by(course_id="algebra", section_id="pages0")
            .count()
        )
        assert review_count_after == 2


def test_generate_lesson_sets_lesson_md(tmp_path, db_url):
    """generate_lesson produces a validated lesson: lesson_md + lesson_status + quiz/cards."""
    stub = StubProvider()
    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)

    # 4 pages, no bookmarks -> single deterministic section "pages0" (ADR-010).
    # Before: chapter has no lesson yet.
    with base.get_session() as session:
        chap = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert chap.lesson_status == "none"
        assert chap.lesson_md is None

    generate_lesson("algebra", "pages0", provider=stub)

    with base.get_session() as session:
        chap = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert chap.lesson_status == "ready"
        assert chap.lesson_md  # non-empty verbose lesson markdown
        assert chap.quiz is not None and len(chap.quiz) > 0
        assert chap.cards is not None and len(chap.cards) > 0


# ---------------------------------------------------------------------------
# ADR-010: zero-LLM ingest + lazy per-chapter plan metadata / title refinement
# ---------------------------------------------------------------------------


def test_ingest_pdfs_makes_zero_provider_calls(tmp_path, db_url):
    """Ingest must never call the LLM provider — outline and plan are both
    deterministic now (bookmark-first / page-window, default_plan)."""
    call_count = 0

    class CountingStub(StubProvider):
        def complete(self, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            return super().complete(*args, **kwargs)

    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=CountingStub())

    assert call_count == 0, "ingest_pdfs must make zero LLM calls (ADR-010)"


def test_ingest_pdfs_no_bookmarks_uses_page_window_fallback(tmp_path, db_url, monkeypatch):
    """A PDF with no embedded TOC falls back to fixed page-range windows, not
    an LLM outline call. A small window size forces multiple chapters so the
    windowing (not just the "one big chapter" case) is exercised."""
    monkeypatch.setenv("SOURCEMIND_FALLBACK_PAGES_PER_CHAPTER", "2")
    stub = StubProvider()
    pdf_path = _build_four_page_pdf(tmp_path)

    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)

    with base.get_session() as session:
        chapters = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra")
            .order_by(models.Chapter.section_id)
            .all()
        )
        section_ids = sorted(ch.section_id for ch in chapters)
        assert section_ids == ["pages0", "pages2"]
        for ch in chapters:
            assert ch.title.startswith("Pages ")
            assert ch.title_status == "placeholder"

        plan_items = (
            session.query(models.PlanItem).filter_by(course_id="algebra").all()
        )
        for pi in plan_items:
            assert pi.objectives == []
            assert pi.importance == "supporting"
            assert pi.prerequisites == []


def _build_pdf_with_front_matter(tmp_path: Path) -> Path:
    """Build a 6-page PDF: 2 front-matter-looking pages (copyright + printed
    TOC) followed by 4 real-content pages — mirrors the real textbook that
    surfaced this bug (title/copyright/dedication/2 TOC pages before Chapter 0)."""
    pdf_path = tmp_path / "front_matter_course.pdf"
    doc = fitz.open()
    front_matter_texts = [
        "Copyright 2020, All Rights Reserved.",
        "Table of Contents\nChapter 1 .......................... 5\nChapter 2 .......................... 12",
    ]
    for text in front_matter_texts:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), text)
    for i in range(4):
        page = doc.new_page(width=612, height=792)
        page.insert_text(
            (72, 72),
            f"The ability to work comfortably with topic {i} is essential to "
            f"success in algebra. This page covers real chapter content in depth.",
        )
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_ingest_pdfs_never_folds_front_matter_into_chapter_one(tmp_path, db_url, monkeypatch):
    """A no-bookmark PDF whose leading pages look like copyright/printed-TOC
    front matter gets a separate "Front Matter" chapter — real chapter 1
    never contains that boilerplate text (regression for the real textbook
    that surfaced this: title/copyright/dedication/TOC pages were folded into
    its first page-window "chapter")."""
    monkeypatch.setenv("SOURCEMIND_FALLBACK_PAGES_PER_CHAPTER", "3")
    stub = StubProvider()
    pdf_path = _build_pdf_with_front_matter(tmp_path)

    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)

    with base.get_session() as session:
        chapters = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra")
            .order_by(models.Chapter.id)
            .all()
        )
        section_ids = [ch.section_id for ch in chapters]
        assert section_ids[0] == "front_matter"

        front = chapters[0]
        assert front.title == "Front Matter"
        assert front.source_pages == [0, 1]
        assert front.title_status is None
        assert front.importance == "peripheral"
        assert "Copyright" in front.body_md
        assert "Table of Contents" in front.body_md

        # Every other chapter's source starts at or after page 2 and its body
        # never contains the front-matter boilerplate.
        for ch in chapters[1:]:
            assert ch.source_pages[0] >= 2
            assert "Copyright" not in ch.body_md
            assert "Table of Contents" not in ch.body_md


def test_ensure_study_lazily_fills_plan_metadata(tmp_path, db_url):
    """First ensure_study call fills objectives/importance/target_words from
    the chapter's own source text (ADR-010); a second call makes no further
    LLM call for metadata since it's already filled."""

    class MetadataStub(StubProvider):
        def complete(self, prompt, *, system="", schema=None, max_tokens=4096):
            if schema is not None and "objectives" in schema.get("properties", {}):
                return {"objectives": ["Understand ratios"], "importance": "core"}
            return super().complete(prompt, system=system, schema=schema, max_tokens=max_tokens)

    stub = MetadataStub()
    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)

    with base.get_session() as session:
        pi = (
            session.query(models.PlanItem)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert pi.objectives == []  # ingest-time deterministic default
        assert pi.importance == "supporting"
        source_words = len(
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
            .body_md.split()
        )

    ensure_study("algebra", "pages0", provider=stub)

    with base.get_session() as session:
        pi = (
            session.query(models.PlanItem)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        chap = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert pi.objectives == ["Understand ratios"]
        assert pi.importance == "core"
        # target_words is recomputed for the newly-learned "core" importance,
        # not left at the ingest-time "supporting" default.
        from SourceMind.backend.pipeline.plan import compute_target_words
        assert pi.target_words == compute_target_words(source_words, "core")
        # Chapter mirrors PlanItem's objectives/importance (get_chapter reads
        # from Chapter, not PlanItem).
        assert chap.objectives == ["Understand ratios"]
        assert chap.importance == "core"

    # Idempotent: calling ensure_plan_metadata again must not re-fill/overwrite.
    ensure_plan_metadata("algebra", "pages0", stub)
    with base.get_session() as session:
        pi = (
            session.query(models.PlanItem)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert pi.objectives == ["Understand ratios"]


def test_generate_lesson_lazily_fills_plan_metadata(tmp_path, db_url):
    """generate_lesson also triggers the lazy metadata fill (not just ensure_study)."""

    class MetadataStub(StubProvider):
        def complete(self, prompt, *, system="", schema=None, max_tokens=4096):
            if schema is not None and "objectives" in schema.get("properties", {}):
                return {"objectives": ["Master fractions"], "importance": "peripheral"}
            return super().complete(prompt, system=system, schema=schema, max_tokens=max_tokens)

    stub = MetadataStub()
    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)

    generate_lesson("algebra", "pages0", provider=stub)

    with base.get_session() as session:
        pi = (
            session.query(models.PlanItem)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert pi.objectives == ["Master fractions"]
        assert pi.importance == "peripheral"


def test_maybe_refine_title_and_job_refine_placeholder_title(tmp_path, db_url):
    """A page-window placeholder title gets claimed, refined, and mirrored to
    PlanItem.title; a chapter that isn't a placeholder is never claimed."""

    class TitleStub(StubProvider):
        def complete(self, prompt, *, system="", schema=None, max_tokens=4096):
            if schema is not None and "title" in schema.get("properties", {}):
                return {"title": "Fractions and Ratios"}
            return super().complete(prompt, system=system, schema=schema, max_tokens=max_tokens)

    stub = TitleStub()
    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)

    with base.get_session() as session:
        chap = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert chap.title_status == "placeholder"
        old_title = chap.title

    claimed = maybe_refine_title("algebra", "pages0")
    assert claimed is True

    with base.get_session() as session:
        chap = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert chap.title_status == "refining"

    # A second claim attempt while "refining" must be a no-op (avoids
    # scheduling duplicate LLM calls for the same chapter).
    assert maybe_refine_title("algebra", "pages0") is False

    run_title_refinement_job("algebra", "pages0", provider=stub)

    with base.get_session() as session:
        chap = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        pi = (
            session.query(models.PlanItem)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert chap.title == "Fractions and Ratios"
        assert chap.title != old_title
        assert chap.title_status == "refined"
        assert pi.title == "Fractions and Ratios"

    # Refined chapters are never re-claimed.
    assert maybe_refine_title("algebra", "pages0") is False


def test_maybe_refine_title_ignores_toc_derived_chapters(tmp_path, db_url, monkeypatch):
    """A chapter whose title came from real bookmarks (title_status=None) must
    never be claimed for refinement — it's already authoritative."""
    from SourceMind.backend.pipeline.service import ingest_materials

    monkeypatch.setattr(
        "SourceMind.backend.pipeline.service.embed_texts",
        lambda texts: [[0.0] * 8 for _ in texts],
    )
    pdf_path = tmp_path / "toc_book.pdf"
    doc = fitz.open()
    for i in range(2):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), f"PDF page {i} algebra content topic section")
    doc.set_toc([[1, "Chapter A", 1], [1, "Chapter B", 2]])
    doc.save(str(pdf_path))
    doc.close()

    ingest_materials("bk", "Book", [{"kind": "pdf", "path": str(pdf_path)}], provider=StubProvider())

    with base.get_session() as session:
        chap = session.query(models.Chapter).filter_by(course_id="bk", section_id="toc0").first()
        assert chap.title_status is None

    assert maybe_refine_title("bk", "toc0") is False


def test_run_title_refinement_job_failure_stays_retryable(tmp_path, db_url):
    """If the LLM call/parse fails, title_status becomes "failed" (not stuck in
    "refining" forever) and the placeholder title is left in place."""

    class FailingTitleStub(StubProvider):
        def complete(self, prompt, *, system="", schema=None, max_tokens=4096):
            if schema is not None and "title" in schema.get("properties", {}):
                raise RuntimeError("simulated failure")
            return super().complete(prompt, system=system, schema=schema, max_tokens=max_tokens)

    stub = FailingTitleStub()
    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)

    assert maybe_refine_title("algebra", "pages0") is True
    run_title_refinement_job("algebra", "pages0", provider=stub)

    with base.get_session() as session:
        chap = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="pages0")
            .first()
        )
        assert chap.title_status == "failed"
        assert chap.title.startswith("Pages ")  # placeholder left untouched

    # "failed" is retryable on the next claim.
    assert maybe_refine_title("algebra", "pages0") is True


def test_reconcile_interrupted_jobs_fails_over_title_refining(tmp_path, db_url):
    with base.get_session() as session:
        session.add(models.Course(id="c1", title="A", status="ready", generation_status="idle"))
        session.add(models.Chapter(
            course_id="c1", section_id="pages0", title="Pages 1-15", title_status="refining",
        ))

    reconcile_interrupted_jobs()

    with base.get_session() as session:
        chap = session.query(models.Chapter).filter_by(course_id="c1", section_id="pages0").first()
        assert chap.title_status == "failed"


# ---------------------------------------------------------------------------
# reconcile_interrupted_jobs
# ---------------------------------------------------------------------------

def test_reconcile_interrupted_jobs(tmp_path, db_url):
    """Rows left mid-job by an unclean restart flip to a failed terminal
    state; rows already idle/terminal are left untouched."""
    with base.get_session() as session:
        session.add(models.Course(
            id="c-ingesting", title="A", status="ingesting", generation_status="idle",
        ))
        session.add(models.Course(
            id="c-running", title="B", status="ready", generation_status="running",
        ))
        session.add(models.Course(
            id="c-ready", title="C", status="ready", generation_status="succeeded",
        ))
        session.add(models.Course(
            id="c-idle", title="D", status="ready", generation_status="idle",
        ))
        session.add(models.Chapter(
            course_id="c-running", section_id="s1", title="Ch1", lesson_status="generating",
        ))
        session.add(models.Chapter(
            course_id="c-ready", section_id="s2", title="Ch2", lesson_status="ready",
        ))

    reconcile_interrupted_jobs()

    with base.get_session() as session:
        c_ingesting = session.get(models.Course, "c-ingesting")
        assert c_ingesting.status == "failed"
        assert c_ingesting.title == "A"  # title left as-is

        c_running = session.get(models.Course, "c-running")
        assert c_running.generation_status == "failed"
        assert c_running.generation_last_error == "interrupted by server restart"
        assert c_running.status == "ready"  # only status=="ingesting" flips course.status

        c_ready = session.get(models.Course, "c-ready")
        assert c_ready.status == "ready"
        assert c_ready.generation_status == "succeeded"  # untouched: terminal already

        c_idle = session.get(models.Course, "c-idle")
        assert c_idle.status == "ready"
        assert c_idle.generation_status == "idle"  # untouched: not mid-job

        ch1 = session.query(models.Chapter).filter_by(course_id="c-running").first()
        assert ch1.lesson_status == "failed"

        ch2 = session.query(models.Chapter).filter_by(course_id="c-ready").first()
        assert ch2.lesson_status == "ready"  # untouched
