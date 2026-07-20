# Highlights in Course Export — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lossless, versioned `highlights.json` to the course-export zip so a user's highlights and notes leave the app with them.

**Architecture:** Extend `export_service.build_export_zip` to write one extra top-level file, `highlights.json`, sourced from `highlights_service.list_highlights(course_id)` (never a raw model re-query — that would emit 0-based page numbers and desync from the 1-based API). Backend-only; the streamed-zip client is unchanged.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, `zipfile`, pytest. Run everything from `smv2/`.

## Global Constraints

- Work is entirely under `smv2/` — never touch repo-root `backend/`/`frontend/` (that is the v1 app).
- `page` crosses 1-based (API/export) ↔ 0-based (DB). The single conversion lives in `highlights_service.to_display_page`. Do NOT re-query the `Highlight` model in the export.
- `highlights.json` is written on EVERY export, `"highlights": []` when none.
- `schema_version` is `1`.
- Reuse the existing `json.dumps(..., default=str)` datetime handling.
- Run the gate from `smv2/`: `./build.sh` (running from repo root gives exit 127).

---

### Task 1: Write `highlights.json` into the export zip

**Files:**
- Modify: `backend/app/services/export_service.py`
- Test: `backend/tests/test_export.py`

**Interfaces:**
- Consumes: `highlights_service.list_highlights(course_id) -> list[dict]` — already page-converted (1-based), ordered by `Section.order_index, Highlight.created_at`; each dict has `id, course_id, section_id, exact, prefix, suffix, occurrence, page, color, surface, note_md, created_at, updated_at`.
- Produces: a zip entry `highlights.json` with shape `{"schema_version": 1, "course_id": str, "highlights": list[dict]}`.

- [ ] **Step 1: Write the failing tests**

Add these two tests to `backend/tests/test_export.py` (the file already imports `io`, `json`, `zipfile`):

```python
def test_export_includes_highlights_json_round_trip(client, ingest_course):
    from conftest import _first_section_id

    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    create = client.post(
        f"/api/courses/{course_id}/highlights",
        json={
            "section_id": section_id,
            "exact": "Foundations",
            "prefix": "Chapter 1: ",
            "suffix": " and more",
            "occurrence": 0,
            "page": 3,
            "color": "green",
            "surface": "pdf",
        },
    )
    assert create.status_code == 201
    created = create.json()

    patch = client.patch(f"/api/highlights/{created['id']}", json={"note_md": "my note"})
    assert patch.status_code == 200

    resp = client.get(f"/api/courses/{course_id}/export")
    assert resp.status_code == 200

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert "highlights.json" in zf.namelist()
        data = json.loads(zf.read("highlights.json").decode("utf-8"))
        assert data["schema_version"] == 1
        assert data["course_id"] == course_id
        assert len(data["highlights"]) == 1

        h = data["highlights"][0]
        assert h["id"] == created["id"]
        assert h["section_id"] == section_id
        assert h["exact"] == "Foundations"
        assert h["page"] == 3          # 1-based, same as the API surface
        assert h["surface"] == "pdf"
        assert h["color"] == "green"
        assert h["note_md"] == "my note"


def test_export_highlights_json_empty_when_none(client, ingest_course):
    course_id, *_ = ingest_course("with_bookmarks.pdf")

    resp = client.get(f"/api/courses/{course_id}/export")
    assert resp.status_code == 200

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert "highlights.json" in zf.namelist()
        data = json.loads(zf.read("highlights.json").decode("utf-8"))
        assert data["schema_version"] == 1
        assert data["course_id"] == course_id
        assert data["highlights"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest backend/tests/test_export.py -k highlights -v`
Expected: FAIL — `KeyError`/`assert "highlights.json" in ...` because the file is not yet written.

- [ ] **Step 3: Implement — write the file in the zip**

In `backend/app/services/export_service.py`, add the service import at the top with the other app imports:

```python
from app.services import highlights_service
```

Then, inside the `with zipfile.ZipFile(spool, ...) as zf:` block, immediately after the `zf.writestr("manifest.json", ...)` line, add:

```python
            highlights_payload = {
                "schema_version": 1,
                "course_id": course.id,
                "highlights": highlights_service.list_highlights(course_id),
            }
            zf.writestr(
                "highlights.json",
                json.dumps(highlights_payload, indent=2, default=str),
            )
```

Note: `list_highlights` opens its own short-lived read session — that is fine alongside the export's open session (independent SQLite reads). Do not inline a `Highlight` query into the export session; that reintroduces the 0-based `page` bug.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest backend/tests/test_export.py -k highlights -v`
Expected: PASS (both new tests).

- [ ] **Step 5: Run the whole export test module (guard the additive change)**

Run: `uv run pytest backend/tests/test_export.py -v`
Expected: PASS — all pre-existing export tests still green (the new file is additive; no section/manifest/lesson assertions change).

- [ ] **Step 6: Full gate**

Run from `smv2/`: `./build.sh`
Expected: backend pytest green, frontend build green (frontend is untouched here). The pre-existing full-suite-only flake `frontend/__tests__/**/test-attempt.test.tsx` is unrelated to this change — note it if it appears, don't chase it.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/export_service.py backend/tests/test_export.py
git commit -m "feat: include highlights.json in course export"
```

(Stage only these two files — leave the pre-existing unstaged `.gitignore` edit alone.)

---

## Self-Review

**Spec coverage:**
- Lossless versioned `highlights.json` at zip root — Task 1, Step 3. ✓
- Sourced from `list_highlights` (single page conversion) — Step 3 + note. ✓
- Flat array, 1-based page, null note/page semantics — asserted in Step 1 tests. ✓
- Always emitted incl. empty `[]` — `test_export_highlights_json_empty_when_none`. ✓
- No frontend / manifest / import changes — nothing in the plan touches them. ✓
- Extend `test_export.py` with round-trip + empty — Step 1. ✓
- No new ADR — none in the plan. ✓

**Placeholder scan:** No TBD/TODO; every code step shows the exact code. ✓

**Type consistency:** `list_highlights(course_id) -> list[dict]` used consistently; payload keys `schema_version`/`course_id`/`highlights` match between implementation (Step 3) and assertions (Step 1). `page == 3` matches the 1-based API. `color == "green"` is a valid `HighlightColor` (`Literal["yellow","green","blue","pink"]`). ✓
