"""E2E + unit tests for the DB-backed library router — Task 11 TDD.

Structure
---------
* StubProvider  — deterministic, no network, recognises schema by key presence
* _db fixture   — autouse; isolates each test in a fresh tmp SQLite database
* client fixture — TestClient with provider_dependency overridden to StubProvider
* End-to-end test through upload → approve → generate → chapter → anki.tsv
* Individual tests for chat, progress, reviews, 404s, uniqueness suffix
"""
from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF
import pytest
from fastapi.testclient import TestClient

from SourceMind.backend.db import base, models
from SourceMind.backend.main import app
from SourceMind.backend.routers.library import provider_dependency

# ─── Shared chapter markdown ──────────────────────────────────────────────────
# Matches the one used in test_pipeline_service.py — already vetted to pass
# parse_quiz / parse_cards / count_worked_examples checks in the pipeline.

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

CHAT_ANSWER = "Based on the chapter content: the fundamental idea is the core concept."


# ─── Stub LLM Provider ────────────────────────────────────────────────────────


class StubProvider:
    """Deterministic provider — never hits the network.

    Branching logic mirrors test_pipeline_service.StubProvider:
    * schema with "sections"  → outline response
    * schema with "items"     → plan response (importance=core, target_words omitted
                                 so generate_plan computes it from source words)
    * schema with "grounded"  → grounding judge passes
    * no schema + "CHAPTER CONTENT" in prompt → canned chat answer
    * no schema               → GOOD_CHAPTER_MD (chapter generation / repair)
    """

    def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        schema: dict | None = None,
        max_tokens: int = 4096,
    ) -> str | dict:
        if schema is not None:
            props = schema.get("properties", {})
            if "sections" in props:
                return {
                    "sections": [
                        {
                            "section_id": "s1",
                            "title": "Core Concepts",
                            "page_start": 0,
                            "page_end": 0,
                        }
                    ]
                }
            if "items" in props:
                return {
                    "items": [
                        {
                            "section_id": "s1",
                            "objectives": ["Understand the fundamentals"],
                            "importance": "core",
                            "prerequisites": [],
                        }
                    ]
                }
            if "grounded" in props:
                return {"grounded": True, "unsupported": []}
            # Fallback for any unrecognised schema
            return {}

        # No schema: distinguish chat from chapter generation / repair
        if "CHAPTER CONTENT" in prompt:
            return CHAT_ANSWER
        return GOOD_CHAPTER_MD


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    """Isolate every test in its own tmp SQLite database; clean up on teardown."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("SOURCEMIND_DB_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SOURCEMIND_ASSETS_DIR", str(tmp_path / "data"))
    base.init_db()
    yield
    base.reset_engine_cache()


@pytest.fixture()
def client():
    """TestClient with StubProvider injected via dependency override."""
    app.dependency_overrides[provider_dependency] = lambda: StubProvider()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(provider_dependency, None)


# ─── PDF builder ──────────────────────────────────────────────────────────────


def _build_pdf(tmp_path: Path) -> Path:
    """Build a minimal 1-page PDF containing a short text line."""
    pdf_path = tmp_path / "test_course.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 72), "Introduction to core concepts and fundamental ideas.")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


# ─── Upload helper ────────────────────────────────────────────────────────────


def _upload(client: TestClient, tmp_path: Path, title: str = "Test Course") -> str:
    """POST /library/uploads and return the course_id."""
    pdf_path = _build_pdf(tmp_path)
    with pdf_path.open("rb") as fh:
        resp = client.post(
            "/library/uploads",
            data={"title": title},
            files=[("files", (pdf_path.name, fh, "application/pdf"))],
        )
    assert resp.status_code == 200, resp.text
    return resp.json()["course_id"]


# ─── End-to-end test ──────────────────────────────────────────────────────────


def test_end_to_end(client: TestClient, tmp_path: Path) -> None:
    """Full pipeline: upload → approve → generate → chapter → anki.tsv."""

    # 1. Upload PDF and get course_id
    course_id = _upload(client, tmp_path)
    assert course_id

    # 2. List courses — our new course appears
    resp = client.get("/library/courses")
    assert resp.status_code == 200
    assert any(c["id"] == course_id for c in resp.json())

    # 3. Course detail — plan and chapter list are populated
    resp = client.get(f"/library/courses/{course_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["course"]["id"] == course_id
    assert len(data["plan"]) >= 1
    section_id = data["plan"][0]["section_id"]
    assert len(data["chapters"]) >= 1

    # 4. Plan endpoint
    resp = client.get(f"/library/courses/{course_id}/plan")
    assert resp.status_code == 200
    plan = resp.json()
    assert plan[0]["section_id"] == section_id

    # 5. Approve plan
    resp = client.post(f"/library/courses/{course_id}/plan/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "generating"

    # 6. Trigger generation (BackgroundTasks run synchronously in TestClient)
    resp = client.post(f"/library/courses/{course_id}/generate")
    assert resp.status_code == 200
    assert resp.json()["status"] == "started"

    # 7. Course should now be "ready" (background ran before client.post returned)
    resp = client.get(f"/library/courses/{course_id}")
    assert resp.status_code == 200
    course_data = resp.json()["course"]
    assert course_data["status"] == "ready", f"Unexpected status: {course_data}"

    # 8. Full chapter — body, quiz, and cards present
    resp = client.get(f"/library/courses/{course_id}/chapters/{section_id}")
    assert resp.status_code == 200
    chapter = resp.json()
    assert chapter["body_md"], "body_md should be non-empty after generation"
    assert chapter["quiz"] and len(chapter["quiz"]) >= 1
    assert chapter["cards"] and len(chapter["cards"]) >= 1
    assert chapter["status"] == "ready"

    # 9. Anki TSV — 3 columns per row, tag contains course_id
    resp = client.get(f"/library/courses/{course_id}/anki.tsv")
    assert resp.status_code == 200
    ct = resp.headers.get("content-type", "")
    assert "tab-separated-values" in ct, f"Unexpected content-type: {ct}"
    tsv = resp.text
    assert tsv.strip(), "TSV should be non-empty"
    for row in tsv.strip().splitlines():
        cols = row.split("\t")
        assert len(cols) == 3, f"Expected 3 columns, got {len(cols)}: {row!r}"
    assert f"sourcemind::{course_id}" in tsv


# ─── Individual endpoint tests ────────────────────────────────────────────────


def test_chat_returns_answer_and_persists_turns(client: TestClient, tmp_path: Path) -> None:
    course_id = _upload(client, tmp_path)
    client.post(f"/library/courses/{course_id}/plan/approve")
    client.post(f"/library/courses/{course_id}/generate")

    resp = client.get(f"/library/courses/{course_id}")
    section_id = resp.json()["plan"][0]["section_id"]

    resp = client.post(
        f"/library/courses/{course_id}/chapters/{section_id}/chat",
        json={"question": "What is the key concept?"},
    )
    assert resp.status_code == 200
    answer = resp.json()["answer"]
    assert answer, "answer should be non-empty"

    # Two ChatTurn rows (user + assistant) must be persisted
    with base.get_session() as session:
        turns = [
            {"role": t.role, "content": t.content}
            for t in session.query(models.ChatTurn)
            .filter_by(course_id=course_id, section_id=section_id)
            .all()
        ]
    assert len(turns) == 2
    assert {t["role"] for t in turns} == {"user", "assistant"}
    user_turn = next(t for t in turns if t["role"] == "user")
    assert user_turn["content"] == "What is the key concept?"


def test_progress_upsert(client: TestClient, tmp_path: Path) -> None:
    course_id = _upload(client, tmp_path)
    resp = client.get(f"/library/courses/{course_id}")
    section_id = resp.json()["plan"][0]["section_id"]

    # First upsert — creates row
    resp = client.post(
        f"/library/courses/{course_id}/chapters/{section_id}/progress",
        json={"completed": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["completed"] is True
    assert data["section_id"] == section_id
    assert data["id"] is not None

    # Second upsert — updates existing row
    resp = client.post(
        f"/library/courses/{course_id}/chapters/{section_id}/progress",
        json={"completed": False},
    )
    assert resp.status_code == 200
    assert resp.json()["completed"] is False

    # Only one row should exist (upsert, not insert twice)
    with base.get_session() as session:
        count = (
            session.query(models.ProgressState)
            .filter_by(course_id=course_id, section_id=section_id)
            .count()
        )
    assert count == 1


def test_reviews_grade_then_due(client: TestClient, tmp_path: Path) -> None:
    course_id = _upload(client, tmp_path)
    resp = client.get(f"/library/courses/{course_id}")
    section_id = resp.json()["plan"][0]["section_id"]

    # Grade a card correctly
    resp = client.post(
        f"/library/courses/{course_id}/reviews/grade",
        json={"section_id": section_id, "card_index": 0, "correct": True},
    )
    assert resp.status_code == 200
    graded = resp.json()
    assert graded["reps"] == 1
    assert graded["interval"] == 1  # SM-2: first correct rep → interval=1

    # Due list — newly graded card has due_at 1 day in the future, so 0 due now
    resp = client.get(f"/library/courses/{course_id}/reviews/due")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_404_unknown_course(client: TestClient) -> None:
    bogus = "nonexistent_course_xyz"

    assert client.get(f"/library/courses/{bogus}").status_code == 404
    assert client.get(f"/library/courses/{bogus}/plan").status_code == 404
    assert client.get(f"/library/courses/{bogus}/chapters/s1").status_code == 404
    assert client.get(f"/library/courses/{bogus}/reviews/due").status_code == 404
    assert client.get(f"/library/courses/{bogus}/anki.tsv").status_code == 404
    assert client.post(f"/library/courses/{bogus}/plan/approve").status_code == 404
    assert client.post(
        f"/library/courses/{bogus}/generate"
    ).status_code == 404


def test_upload_uniqueness_suffix(client: TestClient, tmp_path: Path) -> None:
    """Two uploads with the same title must yield different course_ids."""
    id1 = _upload(client, tmp_path, title="Algebra Basics")
    id2 = _upload(client, tmp_path, title="Algebra Basics")
    assert id1 != id2
    assert id1 == "algebra_basics"
    assert id2.startswith("algebra_basics_")


# ─── Asset serving ────────────────────────────────────────────────────────────


def test_asset_endpoint_serves_file(client: TestClient, tmp_path: Path) -> None:
    """GET /library/courses/{id}/assets/{relpath} returns 200 and the file bytes."""
    course_id = _upload(client, tmp_path)

    from SourceMind.backend.pipeline.service import course_assets_dir

    assets_dir = course_assets_dir(course_id)
    src_dir = assets_dir / "src0"
    src_dir.mkdir(parents=True, exist_ok=True)
    img = src_dir / "test_image.png"
    img.write_bytes(b"\x89PNG_FAKE_BYTES")

    resp = client.get(f"/library/courses/{course_id}/assets/src0/test_image.png")
    assert resp.status_code == 200
    assert resp.content == b"\x89PNG_FAKE_BYTES"


def test_asset_endpoint_404_missing_file(client: TestClient, tmp_path: Path) -> None:
    """GET /library/courses/{id}/assets/{relpath} returns 404 when the file is absent."""
    course_id = _upload(client, tmp_path)
    resp = client.get(f"/library/courses/{course_id}/assets/nonexistent.png")
    assert resp.status_code == 404


def test_asset_endpoint_403_traversal(tmp_path: Path) -> None:
    """Path traversal (../../) in the asset_path parameter is rejected with 403.

    TestClient (httpx-backed) normalises '..' in URL paths before the request
    reaches the router, so this test calls the route function directly to supply
    the raw traversal string — the same string an adversarial HTTP client would
    deliver to the ASGI scope.
    """
    import pytest
    from fastapi import HTTPException

    from SourceMind.backend.db import base, models
    from SourceMind.backend.pipeline.service import course_assets_dir
    from SourceMind.backend.routers.library import get_course_asset

    course_id = "traversal_guard_test"
    with base.get_session() as session:
        session.add(
            models.Course(
                id=course_id,
                title="Guard Test",
                status="ready",
                generation_status="idle",
            )
        )

    assets_dir = course_assets_dir(course_id)
    assets_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(HTTPException) as exc_info:
        get_course_asset(course_id, "../../etc/passwd")
    assert exc_info.value.status_code == 403


def test_asset_endpoint_404_unknown_course(client: TestClient) -> None:
    """GET /library/courses/unknown/assets/img.png returns 404."""
    resp = client.get("/library/courses/nonexistent_xyz/assets/image.png")
    assert resp.status_code == 404


# ─── Plan ordering + completed flag ──────────────────────────────────────────


def test_courses_chapters_in_plan_order(client: TestClient) -> None:
    """Chapters returned by GET /library/courses/{id} follow plan order, not DB insert order."""
    course_id = "order_test_course"
    with base.get_session() as session:
        session.add(
            models.Course(
                id=course_id,
                title="Order Test",
                status="ready",
                generation_status="idle",
            )
        )
        # Chapters inserted in DB order: "a" first, then "b".
        session.add(
            models.Chapter(
                course_id=course_id,
                section_id="a",
                title="Section A",
                status="ready",
                importance="core",
            )
        )
        session.add(
            models.Chapter(
                course_id=course_id,
                section_id="b",
                title="Section B",
                status="ready",
                importance="supplemental",
            )
        )
        # Plan assigns "b" order=0 and "a" order=1 — the reverse of DB order.
        session.add(
            models.PlanItem(
                course_id=course_id, section_id="b", title="Section B", order=0
            )
        )
        session.add(
            models.PlanItem(
                course_id=course_id, section_id="a", title="Section A", order=1
            )
        )

    resp = client.get(f"/library/courses/{course_id}")
    assert resp.status_code == 200
    chapters = resp.json()["chapters"]
    assert len(chapters) == 2
    assert chapters[0]["section_id"] == "b", (
        f"Expected 'b' first (plan order=0), got {chapters[0]['section_id']!r}"
    )
    assert chapters[1]["section_id"] == "a", (
        f"Expected 'a' second (plan order=1), got {chapters[1]['section_id']!r}"
    )


def test_chapter_completed_reflects_progress(client: TestClient) -> None:
    """completed flag per chapter reflects ProgressState; unmarked chapters return False."""
    course_id = "progress_flag_test"
    with base.get_session() as session:
        session.add(
            models.Course(
                id=course_id,
                title="Progress Flag Test",
                status="ready",
                generation_status="idle",
            )
        )
        session.add(
            models.PlanItem(
                course_id=course_id, section_id="s1", title="Section 1", order=0
            )
        )
        session.add(
            models.PlanItem(
                course_id=course_id, section_id="s2", title="Section 2", order=1
            )
        )
        session.add(
            models.Chapter(
                course_id=course_id,
                section_id="s1",
                title="Section 1",
                status="ready",
                importance="core",
            )
        )
        session.add(
            models.Chapter(
                course_id=course_id,
                section_id="s2",
                title="Section 2",
                status="ready",
                importance="core",
            )
        )

    # Mark s1 complete via the progress endpoint.
    resp = client.post(
        f"/library/courses/{course_id}/chapters/s1/progress",
        json={"completed": True},
    )
    assert resp.status_code == 200

    resp = client.get(f"/library/courses/{course_id}")
    assert resp.status_code == 200
    chapters = resp.json()["chapters"]
    assert len(chapters) == 2

    by_sid = {ch["section_id"]: ch for ch in chapters}
    assert by_sid["s1"]["completed"] is True, "s1 should be marked completed"
    assert by_sid["s2"]["completed"] is False, "s2 should not be marked completed"


def test_get_chapter_returns_completed_field(client: TestClient, tmp_path: Path) -> None:
    """GET .../chapters/{sid} includes completed; reflects ProgressState after marking."""
    course_id = _upload(client, tmp_path)
    client.post(f"/library/courses/{course_id}/plan/approve")
    client.post(f"/library/courses/{course_id}/generate")

    resp = client.get(f"/library/courses/{course_id}")
    section_id = resp.json()["plan"][0]["section_id"]

    # Before marking: completed must be present and False
    resp = client.get(f"/library/courses/{course_id}/chapters/{section_id}")
    assert resp.status_code == 200
    chapter = resp.json()
    assert "completed" in chapter, "get_chapter response must include 'completed'"
    assert chapter["completed"] is False, "Expected completed=False before marking"

    # Mark complete via progress endpoint
    client.post(
        f"/library/courses/{course_id}/chapters/{section_id}/progress",
        json={"completed": True},
    )

    # After marking: completed must be True
    resp = client.get(f"/library/courses/{course_id}/chapters/{section_id}")
    assert resp.status_code == 200
    assert resp.json()["completed"] is True, "Expected completed=True after marking"


# ─── Delete course ────────────────────────────────────────────────────────────


def test_delete_course_removes_all_rows(client: TestClient, tmp_path: Path) -> None:
    """DELETE removes the course + all child rows; follow-up GET is 404."""
    course_id = _upload(client, tmp_path)
    client.post(f"/library/courses/{course_id}/plan/approve")
    client.post(f"/library/courses/{course_id}/generate")

    # Sanity: generation seeded review/chapter/plan rows for this course.
    with base.get_session() as session:
        assert session.query(models.ReviewState).filter_by(course_id=course_id).count() >= 1
        assert session.query(models.Chapter).filter_by(course_id=course_id).count() >= 1
        assert session.query(models.PlanItem).filter_by(course_id=course_id).count() >= 1

    # Delete the course.
    resp = client.delete(f"/library/courses/{course_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": True}

    # Follow-up GET is 404.
    assert client.get(f"/library/courses/{course_id}").status_code == 404

    # No child rows remain for the deleted course.
    with base.get_session() as session:
        assert session.query(models.ReviewState).filter_by(course_id=course_id).count() == 0
        assert session.query(models.Chapter).filter_by(course_id=course_id).count() == 0
        assert session.query(models.PlanItem).filter_by(course_id=course_id).count() == 0
        assert session.get(models.Course, course_id) is None

    # Deleting an unknown id is 404.
    assert client.delete("/library/courses/nonexistent_course_xyz").status_code == 404


# ─── Cross-course reviews + notifications ─────────────────────────────────────


def test_reviews_due_all_aggregates(client: TestClient, tmp_path: Path) -> None:
    """GET /library/reviews/due aggregates due cards across courses, joined to text."""
    course_id = _upload(client, tmp_path)
    client.post(f"/library/courses/{course_id}/plan/approve")
    client.post(f"/library/courses/{course_id}/generate")

    resp = client.get("/library/reviews/due")
    assert resp.status_code == 200
    rows = resp.json()
    assert isinstance(rows, list)
    assert len(rows) >= 1, "expected at least one seeded due card after generation"
    for row in rows:
        for key in ("course_id", "course_title", "section_id", "card_index", "q", "a"):
            assert key in row, f"missing key {key!r} in due row {row!r}"
    assert any(row["course_id"] == course_id for row in rows)


def test_notifications_summary(client: TestClient, tmp_path: Path) -> None:
    """GET /library/notifications returns due_review_count + courses list."""
    course_id = _upload(client, tmp_path)

    resp = client.get("/library/notifications")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["due_review_count"], int)
    assert isinstance(data["courses"], list)
    assert any(c["id"] == course_id for c in data["courses"])
    for c in data["courses"]:
        assert "id" in c and "title" in c and "status" in c
