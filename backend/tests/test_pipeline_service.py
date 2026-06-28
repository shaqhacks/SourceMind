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
    generate_course,
    get_image_urls,
    get_source_text,
    ingest_pdfs,
    regenerate_section,
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
        assert course.status == "needs_review"
        assert course.generation_status == "idle"

        plan_items = (
            session.query(models.PlanItem).filter_by(course_id="algebra").all()
        )
        assert len(plan_items) >= 1

        chapters = (
            session.query(models.Chapter).filter_by(course_id="algebra").all()
        )
        assert len(chapters) >= 1
        assert all(ch.status == "pending" for ch in chapters)
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


def test_regenerate_section(tmp_path, db_url):
    stub = StubProvider()
    pdf_path = _build_four_page_pdf(tmp_path)
    ingest_pdfs("algebra", "Algebra", [pdf_path], provider=stub)
    approve_plan("algebra")
    generate_course("algebra", provider=stub)

    # Manually reset s1 to simulate a failed/stale chapter
    with base.get_session() as session:
        ch = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="s1")
            .first()
        )
        assert ch is not None
        ch.body_md = None
        ch.status = "failed"

    regenerate_section("algebra", "s1", provider=stub)

    with base.get_session() as session:
        ch = (
            session.query(models.Chapter)
            .filter_by(course_id="algebra", section_id="s1")
            .first()
        )
        assert ch is not None
        assert ch.status == "ready"
        assert ch.body_md


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
    # Attribute-style (ORM objects / SimpleNamespace)
    assets = [
        SimpleNamespace(path="img0.png", source_page=0),
        SimpleNamespace(path="img1.png", source_page=1),
        SimpleNamespace(path="img2.png", source_page=2),
        SimpleNamespace(path="img3.png", source_page=3),
    ]
    result = get_image_urls(assets, 1, 2)
    assert len(result) == 2
    assert "img1.png" in result
    assert "img2.png" in result

    # Dict-style (mirrors the plain-dict asset_records used in generate_course)
    dict_assets = [
        {"path": "img0.png", "source_page": 0},
        {"path": "img1.png", "source_page": 1},
        {"path": "img2.png", "source_page": 2},
        {"path": "img3.png", "source_page": 3},
    ]
    dict_result = get_image_urls(dict_assets, 1, 2)
    assert len(dict_result) == 2
    assert "img1.png" in dict_result
    assert "img2.png" in dict_result


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

        failed_chapters = [ch for ch in chapters if ch.status == "failed"]
        ready_chapters = [ch for ch in chapters if ch.status == "ready"]

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
