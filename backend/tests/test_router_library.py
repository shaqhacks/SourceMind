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
            if "quiz" in props:
                # generate_study_items schema → fixed quiz + cards
                return {
                    "quiz": [
                        {
                            "q": "What is the core concept?",
                            "options": ["A", "B", "C", "D"],
                            "answer": "A",
                            "explain": "A is the fundamental idea.",
                        },
                    ],
                    "cards": [
                        {"q": "What is the key concept?", "a": "The fundamental idea."},
                        {"q": "How do you apply it?", "a": "By following the steps."},
                    ],
                }
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
    # Also seed Chunk/ReviewLog/TestAttempt directly so the cascade is exercised
    # (embeddings aren't run in tests, so Chunk wouldn't otherwise exist).
    with base.get_session() as session:
        assert session.query(models.ReviewState).filter_by(course_id=course_id).count() >= 1
        assert session.query(models.Chapter).filter_by(course_id=course_id).count() >= 1
        assert session.query(models.PlanItem).filter_by(course_id=course_id).count() >= 1
        session.add(models.Chunk(course_id=course_id, source_ref="p.1",
                                 content="x", embedding=[0.0], chunk_index=0))
        session.add(models.ReviewLog(course_id=course_id, section_id="s1",
                                     card_index=0, quality=2, created_at="2026-01-01T00:00:00+00:00"))
        session.add(models.TestAttempt(course_id=course_id, section_id="s1", scope="section",
                                       answers=[0], correct=1, total=1, score=1.0, passed=True,
                                       created_at="2026-01-01T00:00:00+00:00"))

    # Delete the course.
    resp = client.delete(f"/library/courses/{course_id}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": True}

    # Follow-up GET is 404.
    assert client.get(f"/library/courses/{course_id}").status_code == 404

    # NO child rows remain for the deleted course — across EVERY owned table.
    with base.get_session() as session:
        for child_model in (
            models.ReviewState, models.ReviewLog, models.ProgressState,
            models.Asset, models.Chapter, models.PlanItem,
            models.ChatTurn, models.Chunk, models.TestAttempt,
        ):
            assert session.query(child_model).filter_by(course_id=course_id).count() == 0, child_model.__name__
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


# ─── Test mode endpoints ──────────────────────────────────────────────────────


def test_section_test_submit_persists_attempt(client: TestClient, tmp_path: Path) -> None:
    """Submit a section test → score in response + TestAttempt row persisted + GET attempts returns it."""
    course_id = _upload(client, tmp_path)
    client.post(f"/library/courses/{course_id}/plan/approve")
    client.post(f"/library/courses/{course_id}/generate")

    # 1-page PDF, no bookmarks -> single deterministic section "pages0" (ADR-010).
    # All correct answers: [0, 1, 2, 3]
    resp = client.post(
        f"/library/courses/{course_id}/chapters/pages0/test/submit",
        json={"answers": [0, 1, 2, 3]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["correct"] == 4
    assert data["total"] == 4
    assert data["score"] == pytest.approx(1.0)
    assert data["passed"] is True
    assert "attempt_id" in data
    assert isinstance(data["attempt_id"], int)

    # Verify row persisted in DB
    with base.get_session() as session:
        attempt = session.get(models.TestAttempt, data["attempt_id"])
        assert attempt is not None
        assert attempt.scope == "section"
        assert attempt.section_id == "pages0"
        assert attempt.correct == 4
        assert attempt.passed is True

    # GET attempts returns it
    attempts_resp = client.get(f"/library/courses/{course_id}/chapters/pages0/test/attempts")
    assert attempts_resp.status_code == 200
    attempts = attempts_resp.json()
    assert len(attempts) == 1
    assert attempts[0]["score"] == pytest.approx(1.0)
    assert attempts[0]["passed"] is True


def test_course_test_aggregates(client: TestClient, tmp_path: Path) -> None:
    """Course-level test submit aggregates correct/total across sections."""
    course_id = _upload(client, tmp_path)
    client.post(f"/library/courses/{course_id}/plan/approve")
    client.post(f"/library/courses/{course_id}/generate")

    # 1-page PDF, no bookmarks -> single deterministic section "pages0" (ADR-010).
    # Submit course test with correct answers for that section (4 questions: 0,1,2,3)
    resp = client.post(
        f"/library/courses/{course_id}/test/submit",
        json={"answers": {"pages0": [0, 1, 2, 3]}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["correct"] == 4
    assert data["total"] == 4
    assert data["score"] == pytest.approx(1.0)
    assert data["passed"] is True
    assert "attempt_id" in data
    assert len(data["sections"]) == 1
    assert data["sections"][0]["section_id"] == "pages0"

    # GET course test attempts
    attempts_resp = client.get(f"/library/courses/{course_id}/test/attempts")
    assert attempts_resp.status_code == 200
    attempts = attempts_resp.json()
    assert len(attempts) == 1
    assert attempts[0]["score"] == pytest.approx(1.0)


# ─── Finding 4: duplicate-filename upload ─────────────────────────────────────


def test_upload_two_files_same_name(client: TestClient) -> None:
    """Two uploaded files that share the same basename must not overwrite each other.

    Before the fix, both would write to ``tmp_dir/notes.txt``; the second would
    silently clobber the first and materials would reference the same path twice.
    After the fix, paths are ``0_notes.txt`` / ``1_notes.txt`` — both distinct.
    """
    content_one = ("alpha beta gamma " * 200).strip().encode()
    content_two = ("delta epsilon zeta " * 200).strip().encode()

    resp = client.post(
        "/library/uploads",
        data={"title": "Duplicate Names Test"},
        files=[
            ("files", ("notes.txt", content_one, "text/plain")),
            ("files", ("notes.txt", content_two, "text/plain")),
        ],
    )
    assert resp.status_code == 200, resp.text
    course_id = resp.json()["course_id"]
    assert course_id

    # The course row must exist — the upload accepted both files without error.
    resp = client.get(f"/library/courses/{course_id}")
    assert resp.status_code == 200
    course = resp.json()["course"]

    # After the fix, ingest_materials receives two distinct paths and processes both,
    # so the course ends "ready" (lazy flow).  Before the fix it would silently lose one.
    assert course["status"] == "ready", (
        f"Expected ready (both files ingested); got {course['status']!r}. "
        f"error: {course.get('generation_last_error')!r}"
    )


def test_section_test_404(client: TestClient, tmp_path: Path) -> None:
    """Submit/GET on unknown course or chapter returns 404."""
    resp = client.post("/library/courses/no_such/chapters/s1/test/submit", json={"answers": []})
    assert resp.status_code == 404

    resp = client.get("/library/courses/no_such/chapters/s1/test/attempts")
    assert resp.status_code == 404

    resp = client.post("/library/courses/no_such/test/submit", json={"answers": {}})
    assert resp.status_code == 404

    resp = client.get("/library/courses/no_such/test/attempts")
    assert resp.status_code == 404

    # Existing course but nonexistent chapter → 404
    course_id = _upload(client, tmp_path)
    resp = client.post(
        f"/library/courses/{course_id}/chapters/nonexistent_chapter/test/submit",
        json={"answers": []},
    )
    assert resp.status_code == 404


# ─── Multi-format upload tests (Task 3) ──────────────────────────────────────


def test_upload_txt_file(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    """Upload a .txt file with ~600 words → 200 with course_id; course row exists."""
    monkeypatch.setattr(
        "SourceMind.backend.pipeline.service.embed_texts",
        lambda texts: [[0.0] * 8 for _ in texts],
    )
    words = " ".join(["word"] * 600)
    txt_path = tmp_path / "lecture.txt"
    txt_path.write_text(words)

    with txt_path.open("rb") as fh:
        resp = client.post(
            "/library/uploads",
            files=[("files", ("lecture.txt", fh, "text/plain"))],
        )
    assert resp.status_code == 200, resp.text
    course_id = resp.json()["course_id"]
    assert course_id

    resp = client.get(f"/library/courses/{course_id}")
    assert resp.status_code == 200
    assert resp.json()["course"]["status"] in ("ready", "ingesting")


def test_upload_unsupported_extension(client: TestClient, tmp_path: Path) -> None:
    """Upload a .xyz file → 400 with a descriptive error before any background job."""
    bad_path = tmp_path / "notes.xyz"
    bad_path.write_bytes(b"some data")

    with bad_path.open("rb") as fh:
        resp = client.post(
            "/library/uploads",
            files=[("files", ("notes.xyz", fh, "application/octet-stream"))],
        )
    assert resp.status_code == 400


def test_upload_source_text(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    """POST /library/uploads/source with kind='text' → 200 with course_id; course row exists."""
    monkeypatch.setattr(
        "SourceMind.backend.pipeline.service.embed_texts",
        lambda texts: [[0.0] * 8 for _ in texts],
    )
    resp = client.post(
        "/library/uploads/source",
        json={"kind": "text", "value": "word " * 600},
    )
    assert resp.status_code == 200, resp.text
    course_id = resp.json()["course_id"]
    assert course_id

    resp = client.get(f"/library/courses/{course_id}")
    assert resp.status_code == 200
    assert resp.json()["course"]["id"] == course_id


def test_upload_source_url_no_network(client: TestClient, monkeypatch) -> None:
    """POST /library/uploads/source with kind='url'; run_materials_job is a no-op → 200, placeholder row exists."""
    monkeypatch.setattr(
        "SourceMind.backend.routers.library.service.run_materials_job",
        lambda *a, **k: None,
    )
    resp = client.post(
        "/library/uploads/source",
        json={"kind": "url", "value": "https://example.com", "title": "My URL"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "course_id" in data
    course_id = data["course_id"]

    with base.get_session() as session:
        course = session.get(models.Course, course_id)
        assert course is not None
        assert course.status == "ingesting"


def test_upload_source_unknown_kind(client: TestClient) -> None:
    """POST /library/uploads/source with kind='file' → 422 (pydantic Literal rejects it)."""
    resp = client.post(
        "/library/uploads/source",
        json={"kind": "file", "value": "x"},
    )
    assert resp.status_code == 422


def test_grade_with_quality(client: TestClient, tmp_path: Path) -> None:
    """POST /reviews/grade with quality=3 (easy) on a fresh card → reps=1, interval=6.

    Easy on fresh card (reps=0, interval=0, ease=2.5):
      reps=1, interval=max(6, round(0*2.5*1.3))=max(6,0)=6, ease=2.65
    """
    course_id = _upload(client, tmp_path)
    resp = client.get(f"/library/courses/{course_id}")
    assert resp.status_code == 200
    section_id = resp.json()["plan"][0]["section_id"]

    resp = client.post(
        f"/library/courses/{course_id}/reviews/grade",
        json={"section_id": section_id, "card_index": 0, "quality": 3},
    )
    assert resp.status_code == 200
    graded = resp.json()
    assert graded["reps"] == 1
    assert graded["interval"] == 6  # max(6, round(0*2.5*1.3)) = max(6, 0) = 6


def test_reviews_stats_endpoint(client: TestClient, tmp_path: Path) -> None:
    """GET /library/reviews/stats → 200 with all six expected keys and daily_goal==20."""
    course_id = _upload(client, tmp_path)
    resp = client.get(f"/library/courses/{course_id}")
    section_id = resp.json()["plan"][0]["section_id"]

    # Grade one card so reviewed_today >= 1
    client.post(
        f"/library/courses/{course_id}/reviews/grade",
        json={"section_id": section_id, "card_index": 0, "quality": 2},
    )

    resp = client.get("/library/reviews/stats")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("reviewed_today", "streak_days", "due_count", "total_cards",
                "mastered_count", "daily_goal"):
        assert key in data, f"Missing key: {key}"
    assert data["daily_goal"] == 20
    assert data["reviewed_today"] >= 1


# ─── Lazy study / lesson endpoints ───────────────────────────────────────────


def test_study_endpoint_returns_quiz(client: TestClient, tmp_path: Path) -> None:
    """POST /chapters/{sid}/study lazily generates and returns quiz + cards (200)."""
    course_id = _upload(client, tmp_path)
    resp = client.get(f"/library/courses/{course_id}")
    section_id = resp.json()["plan"][0]["section_id"]

    resp = client.post(
        f"/library/courses/{course_id}/chapters/{section_id}/study"
    )
    assert resp.status_code == 200, resp.text
    chapter = resp.json()
    assert chapter["quiz"] and len(chapter["quiz"]) >= 1
    assert chapter["cards"] and len(chapter["cards"]) >= 1


def test_lesson_endpoint_generates(client: TestClient, tmp_path: Path) -> None:
    """POST /chapters/{sid}/lesson returns generating; the background task (run
    synchronously by TestClient) drives lesson_status to ready with lesson_md."""
    course_id = _upload(client, tmp_path)
    resp = client.get(f"/library/courses/{course_id}")
    section_id = resp.json()["plan"][0]["section_id"]

    resp = client.post(
        f"/library/courses/{course_id}/chapters/{section_id}/lesson"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["lesson_status"] == "generating"

    # TestClient runs the BackgroundTask before returning, so the lesson is ready.
    resp = client.get(f"/library/courses/{course_id}/chapters/{section_id}")
    assert resp.status_code == 200
    chapter = resp.json()
    assert chapter["lesson_status"] == "ready", chapter
    assert chapter["lesson_md"], "lesson_md should be non-empty after generation"


def test_get_chapter_lazily_refines_placeholder_title(client: TestClient, tmp_path: Path) -> None:
    """GET /chapters/{sid} kicks off background placeholder-title refinement
    (ADR-010) without blocking the read: the response that triggers it still
    shows the old placeholder title; a subsequent GET shows the refined one."""

    class TitleStub(StubProvider):
        def complete(self, prompt, *, system="", schema=None, max_tokens=4096):
            if schema is not None and "title" in schema.get("properties", {}):
                return {"title": "Introduction to Core Concepts"}
            return super().complete(prompt, system=system, schema=schema, max_tokens=max_tokens)

    course_id = _upload(client, tmp_path)
    resp = client.get(f"/library/courses/{course_id}")
    section_id = resp.json()["plan"][0]["section_id"]

    # Swap in the title-aware stub only for the refinement calls below (the
    # `client` fixture's default StubProvider doesn't answer the title schema).
    app.dependency_overrides[provider_dependency] = lambda: TitleStub()

    first = client.get(f"/library/courses/{course_id}/chapters/{section_id}")
    assert first.status_code == 200
    assert first.json()["title_status"] == "placeholder"
    assert first.json()["title"].startswith("Pages ")

    # TestClient already ran the scheduled BackgroundTask by the time the call
    # above returned; a fresh GET reveals the refined title.
    second = client.get(f"/library/courses/{course_id}/chapters/{section_id}")
    assert second.status_code == 200
    data = second.json()
    assert data["title"] == "Introduction to Core Concepts"
    assert data["title_status"] == "refined"
