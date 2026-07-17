# Highlights Backend (Plan 1 of 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backend for student highlights/notes: `highlights` table (wiped on re-ingest), CRUD API, and an optional `selection` field on chat so a student can ask about a selected passage.

**Architecture:** Follows the spec at `smv2/docs/superpowers/specs/2026-07-17-highlights-notes-design.md`. Anchors are opaque text-quote selectors (`exact`/`prefix`/`suffix`/`occurrence`) owned by the frontend matcher; the backend stores them verbatim. House layering: Pydantic schema → service → thin router. Chat injects the selected passage plus deterministic surrounding source text ahead of RAG excerpts — retrieval itself is unchanged.

**Tech Stack:** FastAPI + SQLAlchemy 2 (Mapped/mapped_column) + Alembic + SQLite; pytest with `TestClient` and the `StubProvider` LLM stub. This plan is backend-only — plans 2 (source-mode UI) and 3 (PDF pages-mode UI) follow separately, written against the API client this plan generates.

## Global Constraints

- Everything lives under `smv2/` — never touch repo-root `backend/`/`frontend/` (that's the v1 app).
- Backend test cwd is `smv2/backend`: `uv run pytest tests/<file> -q`. The only CI-trusted gate is `./build.sh` from `smv2/`.
- Page numbers: DB stores 0-based; the API surface is 1-based; conversion happens ONLY in the service layer via `sections_service.to_display_page` (schemas.py module docstring is the law).
- Routers import only fastapi/pydantic/app.services/app.schemas/app.config — never SQLAlchemy or `app.db` (enforced by `tests/test_architecture.py`).
- Every FK-bearing model must be registered in `app/db/registry.py` (enforced by `test_derived_tables_registry_covers_all_fk_models`), and every REPLACED table gets its own explicit delete in `_run_ingest` (`app/pipeline/ingest.py:405-420`) — the section diff keeps unchanged section rows, so FK cascade does NOT wipe rows on re-ingest.
- Tests never touch the network; any LLM path uses the `stub_provider` fixture from `tests/conftest.py`.
- `smv2/openapi.json` and `smv2/frontend/lib/api/schema.d.ts` are generated, committed artifacts — regenerate (`uv run python -m app.export_openapi ../openapi.json`, then `npm run gen:api`), never hand-edit.
- Field limits (from the spec): `exact` 1–2000 chars, `prefix`/`suffix` ≤ 64, `note_md` ≤ 20000, colors exactly `yellow|green|blue|pink`, chat context window 1000 chars per side.
- Commit messages: lowercase conventional style (`feat: ...`), ending with the `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` trailer.

---

### Task 1: Highlight model + migration + registry + ADR

**Files:**
- Modify: `smv2/backend/app/db/models.py` (add `Highlight` after `ChatTurn`, ~line 272)
- Create: `smv2/backend/app/db/migrations/versions/0010_highlights.py`
- Modify: `smv2/backend/app/db/registry.py`
- Modify: `smv2/docs/decisions.md` (append ADR-011)
- Test: `smv2/backend/tests/test_highlights.py` (new)

**Interfaces:**
- Consumes: `Base`, `_new_id`, `utcnow` from `app.db.models`; `ingest_course` fixture from conftest.
- Produces: ORM class `Highlight` with columns `id, course_id, section_id, exact, prefix, suffix, occurrence, page, color, note_md, created_at, updated_at` — Tasks 2–4 import it by this exact name; test helpers `_make_highlight(course_id, section_id, **overrides) -> str` and `_highlight_count(course_id) -> int` reused by Task 2.

- [ ] **Step 1: Write the failing test**

Create `smv2/backend/tests/test_highlights.py`:

```python
from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Course, Highlight, Section


def _make_highlight(course_id: str, section_id: str, **overrides) -> str:
    session = get_session()
    try:
        h = Highlight(
            course_id=course_id,
            section_id=section_id,
            exact=overrides.get("exact", "any selected text"),
            prefix=overrides.get("prefix", ""),
            suffix=overrides.get("suffix", ""),
            occurrence=overrides.get("occurrence", 0),
            page=overrides.get("page"),
            color=overrides.get("color", "yellow"),
            note_md=overrides.get("note_md"),
        )
        session.add(h)
        session.commit()
        return h.id
    finally:
        session.close()


def _highlight_count(course_id: str) -> int:
    session = get_session()
    try:
        return session.query(Highlight).filter(Highlight.course_id == course_id).count()
    finally:
        session.close()


def _first_section_id(course_id: str) -> str:
    session = get_session()
    try:
        return session.query(Section.id).filter(Section.course_id == course_id).first()[0]
    finally:
        session.close()


def test_highlight_persists_and_cascades_with_course(ingest_course):
    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(course_id)

    _make_highlight(course_id, section_id, note_md="remember this")
    assert _highlight_count(course_id) == 1

    # DB-level FK cascade (PRAGMA foreign_keys is ON engine-wide, see
    # test_pragmas.py) — deleting the course row must take highlights with it.
    session = get_session()
    try:
        session.delete(session.get(Course, course_id))
        session.commit()
    finally:
        session.close()
    assert _highlight_count(course_id) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run (cwd `smv2/backend`): `uv run pytest tests/test_highlights.py -q`
Expected: FAIL at import — `ImportError: cannot import name 'Highlight'`.

- [ ] **Step 3: Add the model**

In `smv2/backend/app/db/models.py`, insert after the `ChatTurn` class (before `class Test`):

```python
class Highlight(Base):
    """A user-created highlight/note anchored to a section's body_md by
    text quote (exact/prefix/suffix/occurrence), never by DOM position or
    char offset — the same selection must be locatable in more than one
    rendering of the text (markdown DOM, pdf.js text layer). The anchor is
    opaque to the backend; the frontend matcher owns its semantics.
    Wiped on re-ingest (REPLACED bucket, ADR-011): re-uploading a course's
    PDF deletes its highlights — the upload UI must warn.
    page is 0-based per-asset storage, converted at the service boundary
    like Section.page_start.
    """

    __tablename__ = "highlights"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    section_id: Mapped[str] = mapped_column(
        String, ForeignKey("sections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    exact: Mapped[str] = mapped_column(Text, nullable=False)
    prefix: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    suffix: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    occurrence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    color: Mapped[str] = mapped_column(String, nullable=False, default="yellow")
    note_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
```

- [ ] **Step 4: Create the migration**

Create `smv2/backend/app/db/migrations/versions/0010_highlights.py`:

```python
"""highlights table

Revision ID: 0010_highlights
Revises: 0009_inline_practice_assessments
Create Date: 2026-07-17

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_highlights"
down_revision: Union[str, None] = "0009_inline_practice_assessments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "highlights",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("section_id", sa.String(), nullable=False),
        sa.Column("exact", sa.Text(), nullable=False),
        sa.Column("prefix", sa.String(length=64), nullable=False),
        sa.Column("suffix", sa.String(length=64), nullable=False),
        sa.Column("occurrence", sa.Integer(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("color", sa.String(), nullable=False),
        sa.Column("note_md", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_highlights_course_id", "highlights", ["course_id"])
    op.create_index("ix_highlights_section_id", "highlights", ["section_id"])


def downgrade() -> None:
    op.drop_index("ix_highlights_section_id", table_name="highlights")
    op.drop_index("ix_highlights_course_id", table_name="highlights")
    op.drop_table("highlights")
```

- [ ] **Step 5: Register in the re-ingest registry**

In `smv2/backend/app/db/registry.py`: add `Highlight,` to the `from app.db.models import (...)` block (alphabetical — between `Concept` and `LlmCall` group, i.e. after `ConceptMasteryEvent,`), and add `Highlight,` to `REPLACED_ON_REINGEST` (after `ChatTurn,`, keeping the existing grouping).

- [ ] **Step 6: Run tests to verify pass**

Run (cwd `smv2/backend`): `uv run pytest tests/test_highlights.py tests/test_architecture.py -q`
Expected: PASS. (If Step 5 were skipped, `test_derived_tables_registry_covers_all_fk_models` fails naming `highlights` — that's the enforcement working.)

- [ ] **Step 7: Append ADR-011**

Append to `smv2/docs/decisions.md` (match the heading/format style of the existing ADR-010 entry in that file — this is v2's log, NOT the repo-root `docs/decisions.md`):

```markdown
## ADR-011: Highlights are wiped on re-ingest; text-quote anchors (2026-07-17)

The `highlights` table (student highlights/notes: exact/prefix/suffix/
occurrence text-quote anchor + optional 0-based page + note_md) is
classified REPLACED_ON_REINGEST — re-uploading a course's PDF deletes its
highlights, and the upload UI must warn. Owner explicitly chose this over
remap-survival for the first build (spec:
docs/superpowers/specs/2026-07-17-highlights-notes-design.md); upgrading
to remap-survival later is additive. Anchors are text-quote based, not
CFI/DOM-position or char-offset based, because the same source text
renders in multiple DOMs (react-markdown, pdf.js text layer). The feature
is readest-inspired but uses zero readest code — readest's UI is AGPL-3.0
and must never be copied into this repo.
```

- [ ] **Step 8: Commit**

```bash
cd /Users/shaquillejohnson/code/SourceMind && git add smv2/backend/app/db/models.py smv2/backend/app/db/migrations/versions/0010_highlights.py smv2/backend/app/db/registry.py smv2/backend/tests/test_highlights.py smv2/docs/decisions.md && git commit -m "feat: add highlight model, migration, and reingest registry entry

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Wipe highlights on re-ingest

**Files:**
- Modify: `smv2/backend/app/pipeline/ingest.py` (import block ~line 39-54; delete block ~line 405-420)
- Test: `smv2/backend/tests/test_highlights.py`

**Interfaces:**
- Consumes: `Highlight` model (Task 1); `_make_highlight`/`_highlight_count`/`_first_section_id` helpers (Task 1).
- Produces: the re-ingest wipe guarantee Tasks 3–4 and the frontend plans rely on.

- [ ] **Step 1: Write the failing test**

Append to `smv2/backend/tests/test_highlights.py`:

```python
def test_reingest_wipes_highlights(client, ingest_course):
    from app.jobs.worker import run_due_jobs_once

    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    _make_highlight(course_id, _first_section_id(course_id))
    assert _highlight_count(course_id) == 1

    # Identical re-ingest: the section diff KEEPS every section row (same
    # content-addressed ids), so FK cascade never fires — only the explicit
    # REPLACED-bucket delete in _run_ingest can wipe these rows. That
    # explicit delete is exactly what this asserts.
    ingest_resp = client.post(f"/api/courses/{course_id}/ingest")
    assert ingest_resp.status_code == 202
    assert run_due_jobs_once() is True
    assert _highlight_count(course_id) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run (cwd `smv2/backend`): `uv run pytest tests/test_highlights.py::test_reingest_wipes_highlights -q`
Expected: FAIL — `assert 1 == 0` on the final line (the highlight survived).

- [ ] **Step 3: Add the explicit delete**

In `smv2/backend/app/pipeline/ingest.py`: add `Highlight,` to the `from app.db.models import (...)` block (after `Course,`... alphabetically: between `Course,`/`Job,` — i.e. after `Course,` insert `Highlight,` before `Job,`). Then in the REPLACED delete block, directly after the `session.query(ChatTurn)...` line (line ~405), add:

```python
    session.query(Highlight).filter(Highlight.course_id == course_id).delete()
```

- [ ] **Step 4: Run tests to verify pass**

Run (cwd `smv2/backend`): `uv run pytest tests/test_highlights.py tests/test_reingest_idempotency.py -q`
Expected: PASS (both the new wipe test and the existing survive/replace regressions).

- [ ] **Step 5: Commit**

```bash
cd /Users/shaquillejohnson/code/SourceMind && git add smv2/backend/app/pipeline/ingest.py smv2/backend/tests/test_highlights.py && git commit -m "feat: wipe highlights on reingest

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Highlights CRUD API

**Files:**
- Modify: `smv2/backend/app/schemas.py` (new section before `# --- Chat`)
- Create: `smv2/backend/app/services/highlights_service.py`
- Create: `smv2/backend/app/routers/highlights.py`
- Modify: `smv2/backend/app/main.py` (router import list ~line 15-32; includes ~line 80-91)
- Test: `smv2/backend/tests/test_highlights.py`

**Interfaces:**
- Consumes: `Highlight` model; `sections_service.to_display_page`; `courses_service.get_course`.
- Produces (plan 2's frontend client consumes these via the generated schema): operations `list_highlights` (GET `/api/courses/{course_id}/highlights` → `list[HighlightOut]`), `create_highlight` (POST same path, body `HighlightIn`, 201 → `HighlightOut`), `update_highlight` (PATCH `/api/highlights/{highlight_id}`, body `HighlightUpdateIn` → `HighlightOut`), `delete_highlight` (DELETE same path → 204). Service functions: `list_highlights(course_id) -> list[dict]`, `create_highlight(course_id, *, section_id, exact, prefix, suffix, occurrence, page, color) -> dict` (raises `InvalidSectionForCourseError`), `update_highlight(highlight_id, fields: dict) -> dict | None`, `delete_highlight(highlight_id) -> bool`.

- [ ] **Step 1: Write the failing tests**

Append to `smv2/backend/tests/test_highlights.py`:

```python
def test_highlights_crud_roundtrip(client, ingest_course):
    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    first, second = sections[0], sections[1]

    created = client.post(
        f"/api/courses/{course_id}/highlights",
        json={
            "section_id": second["id"],
            "exact": "any selected text",
            "prefix": "before ",
            "suffix": " after",
            "occurrence": 0,
            "page": second["page_start"],
            "color": "green",
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["color"] == "green"
    assert body["note_md"] is None
    # 1-based in, 1-based out — the DB's 0-based storage never leaks.
    assert body["page"] == second["page_start"]

    later = client.post(
        f"/api/courses/{course_id}/highlights",
        json={"section_id": first["id"], "exact": "other selected text"},
    )
    assert later.status_code == 201

    listed = client.get(f"/api/courses/{course_id}/highlights").json()
    # Ordered by section order_index then created_at — NOT insertion order.
    assert [h["section_id"] for h in listed] == [first["id"], second["id"]]

    hid = body["id"]
    patched = client.patch(f"/api/highlights/{hid}", json={"note_md": "why does this matter?"})
    assert patched.status_code == 200
    assert patched.json()["note_md"] == "why does this matter?"
    assert patched.json()["color"] == "green"  # untouched: PATCH is exclude_unset

    cleared = client.patch(f"/api/highlights/{hid}", json={"note_md": None})
    assert cleared.status_code == 200
    assert cleared.json()["note_md"] is None

    assert client.delete(f"/api/highlights/{hid}").status_code == 204
    assert client.patch(f"/api/highlights/{hid}", json={"color": "pink"}).status_code == 404
    assert client.delete(f"/api/highlights/{hid}").status_code == 404


def test_highlight_validation(client, ingest_course):
    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    other = client.post("/api/courses", json={"title": "Other"}).json()["id"]
    section_id = client.get(f"/api/courses/{course_id}/sections").json()[0]["id"]

    assert client.get("/api/courses/nope/highlights").status_code == 404
    assert client.post(
        "/api/courses/nope/highlights", json={"section_id": section_id, "exact": "x"}
    ).status_code == 404

    # Section from a different course -> 422, same contract as save_progress.
    resp = client.post(
        f"/api/courses/{other}/highlights",
        json={"section_id": section_id, "exact": "x"},
    )
    assert resp.status_code == 422

    # Pydantic-level rejects: empty exact, unknown color, 0 page (1-based API).
    for bad in (
        {"section_id": section_id, "exact": ""},
        {"section_id": section_id, "exact": "x", "color": "mauve"},
        {"section_id": section_id, "exact": "x", "page": 0},
    ):
        assert client.post(f"/api/courses/{course_id}/highlights", json=bad).status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run (cwd `smv2/backend`): `uv run pytest tests/test_highlights.py -q`
Expected: the two new tests FAIL with 404s on `/highlights` (routes don't exist); earlier tests still pass.

- [ ] **Step 3: Add schemas**

In `smv2/backend/app/schemas.py`, insert before the `# --- Chat` section:

```python
# --- Highlights ------------------------------------------------------------


HighlightColor = Literal["yellow", "green", "blue", "pink"]


class HighlightIn(BaseModel):
    """Anchor fields are opaque to the backend — the frontend's quote
    matcher owns their semantics. page is 1-based here like every page in
    this API surface (see module docstring)."""

    section_id: str
    exact: str = Field(min_length=1, max_length=2000)
    prefix: str = Field(default="", max_length=64)
    suffix: str = Field(default="", max_length=64)
    occurrence: int = Field(default=0, ge=0)
    page: int | None = Field(default=None, ge=1)
    color: HighlightColor = "yellow"


class HighlightUpdateIn(BaseModel):
    """PATCH semantics via model_dump(exclude_unset=True): an omitted field
    is left alone; an explicit null note_md clears the note."""

    note_md: str | None = Field(default=None, max_length=20000)
    color: HighlightColor | None = None


class HighlightOut(BaseModel):
    id: str
    course_id: str
    section_id: str
    exact: str
    prefix: str
    suffix: str
    occurrence: int
    page: int | None
    color: HighlightColor
    note_md: str | None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Add the service**

Create `smv2/backend/app/services/highlights_service.py`:

```python
"""Highlights: user-created text-quote annotations on a section's source
text (ADR-011). The anchor (exact/prefix/suffix/occurrence) is stored
opaquely — the frontend matcher owns its semantics. Page numbers cross
this boundary 1-based (API) <-> 0-based (DB), the same single-conversion
rule as sections_service.
"""

from __future__ import annotations

from typing import Any

from app.db.engine import get_session
from app.db.models import Highlight, Section, utcnow
from app.services.sections_service import to_display_page


class InvalidSectionForCourseError(ValueError):
    pass


def _to_dict(h: Highlight) -> dict[str, Any]:
    return {
        "id": h.id,
        "course_id": h.course_id,
        "section_id": h.section_id,
        "exact": h.exact,
        "prefix": h.prefix,
        "suffix": h.suffix,
        "occurrence": h.occurrence,
        "page": to_display_page(h.page),
        "color": h.color,
        "note_md": h.note_md,
        "created_at": h.created_at,
        "updated_at": h.updated_at,
    }


def list_highlights(course_id: str) -> list[dict[str, Any]]:
    session = get_session()
    try:
        rows = (
            session.query(Highlight)
            .join(Section, Section.id == Highlight.section_id)
            .filter(Highlight.course_id == course_id)
            .order_by(Section.order_index, Highlight.created_at)
            .all()
        )
        return [_to_dict(h) for h in rows]
    finally:
        session.close()


def create_highlight(
    course_id: str,
    *,
    section_id: str,
    exact: str,
    prefix: str,
    suffix: str,
    occurrence: int,
    page: int | None,
    color: str,
) -> dict[str, Any]:
    session = get_session()
    try:
        section = session.get(Section, section_id)
        if section is None or section.course_id != course_id:
            raise InvalidSectionForCourseError(
                f"section {section_id} does not belong to course {course_id}"
            )
        h = Highlight(
            course_id=course_id,
            section_id=section_id,
            exact=exact,
            prefix=prefix,
            suffix=suffix,
            occurrence=occurrence,
            page=page - 1 if page is not None else None,
            color=color,
        )
        session.add(h)
        session.commit()
        return _to_dict(h)
    finally:
        session.close()


def update_highlight(highlight_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    """fields comes from HighlightUpdateIn.model_dump(exclude_unset=True):
    absent key = leave alone; note_md explicitly null = clear the note. A
    null color is a no-op (there is no 'no color' state to reset to).
    """
    session = get_session()
    try:
        h = session.get(Highlight, highlight_id)
        if h is None:
            return None
        if "note_md" in fields:
            h.note_md = fields["note_md"]
        if fields.get("color") is not None:
            h.color = fields["color"]
        h.updated_at = utcnow()
        session.commit()
        return _to_dict(h)
    finally:
        session.close()


def delete_highlight(highlight_id: str) -> bool:
    session = get_session()
    try:
        h = session.get(Highlight, highlight_id)
        if h is None:
            return False
        session.delete(h)
        session.commit()
        return True
    finally:
        session.close()
```

- [ ] **Step 5: Add the thin router and wire it**

Create `smv2/backend/app/routers/highlights.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import HighlightIn, HighlightOut, HighlightUpdateIn
from app.services import courses_service, highlights_service

# Course-scoped list/create.
router = APIRouter(prefix="/api/courses", tags=["highlights"])

# Item ops get their own top-level prefix — highlight ids are globally
# unique UUIDs, same pattern as sections.section_router.
highlight_router = APIRouter(prefix="/api/highlights", tags=["highlights"])


@router.get(
    "/{course_id}/highlights", operation_id="list_highlights", response_model=list[HighlightOut]
)
def list_highlights(course_id: str) -> list[HighlightOut]:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return [HighlightOut.model_validate(h) for h in highlights_service.list_highlights(course_id)]


@router.post(
    "/{course_id}/highlights",
    operation_id="create_highlight",
    response_model=HighlightOut,
    status_code=201,
)
def create_highlight(course_id: str, body: HighlightIn) -> HighlightOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    try:
        result = highlights_service.create_highlight(
            course_id,
            section_id=body.section_id,
            exact=body.exact,
            prefix=body.prefix,
            suffix=body.suffix,
            occurrence=body.occurrence,
            page=body.page,
            color=body.color,
        )
    except highlights_service.InvalidSectionForCourseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return HighlightOut.model_validate(result)


@highlight_router.patch(
    "/{highlight_id}", operation_id="update_highlight", response_model=HighlightOut
)
def update_highlight(highlight_id: str, body: HighlightUpdateIn) -> HighlightOut:
    result = highlights_service.update_highlight(highlight_id, body.model_dump(exclude_unset=True))
    if result is None:
        raise HTTPException(status_code=404, detail="highlight not found")
    return HighlightOut.model_validate(result)


@highlight_router.delete("/{highlight_id}", operation_id="delete_highlight", status_code=204)
def delete_highlight(highlight_id: str) -> None:
    if not highlights_service.delete_highlight(highlight_id):
        raise HTTPException(status_code=404, detail="highlight not found")
```

In `smv2/backend/app/main.py`: add `highlights,` to the `from app.routers import (...)` list (alphabetically, between `health,` and `images,`), and after the `app.include_router(sections.section_router)` line add:

```python
    app.include_router(highlights.router)
    app.include_router(highlights.highlight_router)
```

- [ ] **Step 6: Run tests to verify pass**

Run (cwd `smv2/backend`): `uv run pytest tests/test_highlights.py tests/test_architecture.py -q`
Expected: PASS (architecture test confirms the router stayed thin — no `app.db` import).

- [ ] **Step 7: Regenerate the OpenAPI schema + frontend client**

Run (cwd `smv2/backend`): `uv run python -m app.export_openapi ../openapi.json`
Run (cwd `smv2/frontend`): `npm run gen:api`
Expected: `smv2/openapi.json` and `smv2/frontend/lib/api/schema.d.ts` now contain the four `*_highlight*` operations. Then (cwd `smv2/frontend`): `npm run typecheck` — Expected: PASS (additive schema change).

- [ ] **Step 8: Commit**

```bash
cd /Users/shaquillejohnson/code/SourceMind && git add smv2/backend/app/schemas.py smv2/backend/app/services/highlights_service.py smv2/backend/app/routers/highlights.py smv2/backend/app/main.py smv2/backend/tests/test_highlights.py smv2/openapi.json smv2/frontend/lib/api/schema.d.ts && git commit -m "feat: add highlights crud api

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Chat selection scoping

**Files:**
- Modify: `smv2/backend/app/schemas.py` (`ChatIn`, ~line 434)
- Modify: `smv2/backend/app/services/chat_service.py` (`send_chat` ~line 205; new helpers near `_build_excerpts_block` ~line 68)
- Modify: `smv2/backend/app/routers/chat.py` (`send_chat` route, ~line 13-28)
- Test: `smv2/backend/tests/test_chat_selection.py` (new)

**Interfaces:**
- Consumes: `Section` (already imported in chat_service), `stub_provider` fixture (records `received_messages`).
- Produces: `ChatIn.selection: ChatSelectionIn | None` (`ChatSelectionIn = {section_id: str, exact: str}`); `chat_service.send_chat(course_id, message, selection: dict | None = None)`; new exception `chat_service.SelectionSectionMismatchError` → HTTP 422. Plan 2's "Explain" action sends this field.

- [ ] **Step 1: Write the failing tests**

Create `smv2/backend/tests/test_chat_selection.py`:

```python
from __future__ import annotations


def _first_section(client, course_id: str) -> dict:
    sections = client.get(f"/api/courses/{course_id}/sections").json()
    return client.get(f"/api/sections/{sections[0]['id']}").json()


def test_selection_block_injected_before_excerpts(client, ingest_course, stub_provider):
    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    section = _first_section(client, course_id)
    exact = section["body_md"][:40]

    resp = client.post(
        f"/api/courses/{course_id}/chat",
        json={
            "message": "explain this",
            "selection": {"section_id": section["id"], "exact": exact},
        },
    )
    assert resp.status_code == 200

    # The current turn is the LAST message of the LAST call's message list.
    sent = stub_provider.received_messages[-1][-1]["content"]
    assert "<selected_passage>" in sent
    assert exact in sent
    # Spec: selected passage comes AHEAD of the RAG excerpts.
    assert sent.index("<selected_passage>") < sent.index("<excerpts>")


def test_selection_section_of_other_course_is_422(client, ingest_course, stub_provider):
    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    section = _first_section(client, course_id)
    other = client.post("/api/courses", json={"title": "Other"}).json()["id"]

    resp = client.post(
        f"/api/courses/{other}/chat",
        json={"message": "explain", "selection": {"section_id": section["id"], "exact": "x"}},
    )
    assert resp.status_code == 422
    # Rejected BEFORE any provider call — no spend, no turn persisted.
    assert stub_provider.call_count == 0
    assert client.get(f"/api/courses/{other}/chat").json() == []


def test_selection_stored_as_blockquote_in_history(client, ingest_course, stub_provider):
    course_id, _, _, _ = ingest_course("with_bookmarks.pdf")
    section = _first_section(client, course_id)
    exact = section["body_md"][:40]

    client.post(
        f"/api/courses/{course_id}/chat",
        json={
            "message": "explain this",
            "selection": {"section_id": section["id"], "exact": exact},
        },
    )
    history = client.get(f"/api/courses/{course_id}/chat").json()
    user_turns = [t for t in history if t["role"] == "user"]
    assert user_turns[-1]["content"].startswith("> ")
    assert "explain this" in user_turns[-1]["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run (cwd `smv2/backend`): `uv run pytest tests/test_chat_selection.py -q`
Expected: FAIL — first/third tests get 422 (unknown `selection` field is actually ignored by default pydantic... concretely: the assertions on `<selected_passage>`/blockquote fail because nothing injects them; second test fails with 404-vs-422 or `call_count == 1`).

- [ ] **Step 3: Extend the schema**

In `smv2/backend/app/schemas.py`, replace the existing `ChatIn` (keep it in the `# --- Chat` section):

```python
class ChatSelectionIn(BaseModel):
    """A passage the student selected in the reader — same 2000-char cap as
    HighlightIn.exact. Grounds this turn in that passage (ADR-011 feature)."""

    section_id: str
    exact: str = Field(min_length=1, max_length=2000)


class ChatIn(BaseModel):
    message: str
    selection: ChatSelectionIn | None = None
```

- [ ] **Step 4: Extend chat_service**

In `smv2/backend/app/services/chat_service.py`:

Add after the `CourseNotFoundError` class:

```python
class SelectionSectionMismatchError(ValueError):
    pass
```

Add after `_build_excerpts_block`:

```python
_SELECTION_CONTEXT_CHARS = 1000


def _quoted_md(text: str) -> str:
    return "\n".join(f"> {line}" for line in text.splitlines())


def _build_selection_block(section: Section, exact: str) -> str:
    """Deterministic passage grounding: the quote plus up to
    _SELECTION_CONTEXT_CHARS of surrounding body_md on each side
    (first-occurrence match). A verbatim miss should be impossible —
    body_md is immutable and the client sends the text it read — so on a
    miss (stale/forged anchor) degrade to the quote alone, never error.
    """
    body = section.body_md or ""
    idx = body.find(exact)
    if idx == -1:
        surrounding = exact
    else:
        start = max(0, idx - _SELECTION_CONTEXT_CHARS)
        end = min(len(body), idx + len(exact) + _SELECTION_CONTEXT_CHARS)
        surrounding = body[start:end]
    return (
        f'The student selected this passage in section "{section.title}" and is asking about it:\n'
        f"<selected_text>\n{exact}\n</selected_text>\n"
        f"<surrounding_source>\n{surrounding}\n</surrounding_source>"
    )
```

Change `send_chat`'s signature and body:

```python
def send_chat(course_id: str, message: str, selection: dict | None = None) -> dict[str, Any]:
```

Directly after the `CourseNotFoundError` raise (before `provider = get_provider()`), add — validation must precede ALL work so a bad selection costs nothing:

```python
        selection_block = None
        if selection is not None:
            sel_section = session.get(Section, selection["section_id"])
            if sel_section is None or sel_section.course_id != course_id:
                raise SelectionSectionMismatchError(
                    f"section {selection['section_id']} does not belong to course {course_id}"
                )
            selection_block = _build_selection_block(sel_section, selection["exact"])
```

Replace the `user_parts = [f"<excerpts>..."]` line with:

```python
        user_parts = []
        if selection_block:
            user_parts.append(f"<selected_passage>\n{selection_block}\n</selected_passage>")
        user_parts.append(f"<excerpts>\n{excerpts_block}\n</excerpts>")
```

Replace the user-turn persistence line (`session.add(ChatTurn(course_id=course_id, role="user", content=message))`) with — the stored turn carries the quote as a markdown blockquote so history (and its replay via `_build_history_messages`) shows what was asked about, with no schema change:

```python
        stored_user_content = (
            f"{_quoted_md(selection['exact'])}\n\n{message}" if selection is not None else message
        )
        session.add(ChatTurn(course_id=course_id, role="user", content=stored_user_content))
```

Retrieval (`rank_chunks(session, course_id, message, ...)`) stays keyed on `message` alone — per the spec, retrieval is unchanged.

- [ ] **Step 5: Extend the router**

In `smv2/backend/app/routers/chat.py`, replace the `send_chat` call and add the new except clause (first, most-specific):

```python
    try:
        result = chat_service.send_chat(
            course_id,
            body.message,
            selection=body.selection.model_dump() if body.selection else None,
        )
    except chat_service.SelectionSectionMismatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except chat_service.CourseNotFoundError as exc:
```

(remaining except clauses unchanged.)

- [ ] **Step 6: Run tests to verify pass**

Run (cwd `smv2/backend`): `uv run pytest tests/test_chat_selection.py tests/test_chat.py -q`
Expected: PASS — including all pre-existing chat tests (no-selection behavior is byte-identical: same prompt parts, same stored content).

- [ ] **Step 7: Regenerate schema + client**

Run (cwd `smv2/backend`): `uv run python -m app.export_openapi ../openapi.json`
Run (cwd `smv2/frontend`): `npm run gen:api`, then `npm run typecheck`
Expected: `ChatIn` gains optional `selection`; typecheck PASS (optional field, additive).

- [ ] **Step 8: Commit**

```bash
cd /Users/shaquillejohnson/code/SourceMind && git add smv2/backend/app/schemas.py smv2/backend/app/services/chat_service.py smv2/backend/app/routers/chat.py smv2/backend/tests/test_chat_selection.py smv2/openapi.json smv2/frontend/lib/api/schema.d.ts && git commit -m "feat: scope chat to a selected passage

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Full gate

**Files:** none (verification only; fixes commit to whichever file broke)

**Interfaces:** consumes everything above; produces the green gate plans 2–3 build on.

- [ ] **Step 1: Run the full backend suite**

Run (cwd `smv2/backend`): `uv run pytest -q`
Expected: PASS, zero failures.

- [ ] **Step 2: Run the CI-mirror gate**

Run (cwd `smv2/`): `./build.sh`
Expected: every stage green — backend compile+tests, OpenAPI export (must produce NO diff in `smv2/openapi.json`; a diff means Task 3/4 forgot a regen — regenerate and amend that task's commit), frontend deps + client-gen (same no-diff rule for `schema.d.ts`) + typecheck + tests + build.

- [ ] **Step 3: Report**

Report gate output verbatim in the completion summary. If any stage failed, fix forward (smallest change), re-run `./build.sh`, and note the failure + fix in the summary — never claim done on a partial gate.

---

## Deviations from the spec (deliberate, small)

1. **List ordering:** the spec says "section order, then in-text position" — there is no stored in-text position (quote anchors, by design), so ordering is section order then `created_at`. Plan 2 can sort within a section client-side after anchor resolution if it matters visually.
2. **Chat transcript chip:** the spec's "quoted-passage chip" is realized backend-side as a markdown blockquote prefix on the stored user turn (zero schema change, survives history reload); plan 2 may still render it as a styled chip.
3. **Chat system prompt untouched:** the injected `<selected_passage>` block is self-describing; no `backend/prompts/` version bump (avoids touching the prompt-versioning machinery). Revisit only if explain-quality disappoints.
