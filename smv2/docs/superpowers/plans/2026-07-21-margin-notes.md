# Margin Notes (Pages view) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Spec: `docs/superpowers/specs/2026-07-21-margin-notes-design.md`.

**Goal:** Let a student drop a free-standing note in the margin beside a PDF page, anchored to a vertical position, persisted, and listed in the NotesPanel — no text selection required.

**Architecture:** New backend `Note` entity (page + `anchor_y` fraction), mirroring `Highlight`'s service/schema/router shape. Frontend renders note pins in the PDF page's gutter via CSS `top: {anchor_y*100}%` (zoom/resize-stable, no JS geometry). Backend-first (Phases 1–3), then frontend (Phases 4–6), then ADR + gate (Phase 7).

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, SQLite (backend); Next.js 16 / React 19 / TS / Tailwind v4 / Vitest (frontend). pdf.js text layer.

## Global Constraints

- Work is entirely under `smv2/` — never repo-root `backend/`/`frontend/` (v1).
- **Page crosses 1-based (API) ↔ 0-based (DB); the single conversion is `sections_service.to_display_page`.** `notes_service` must route every read through it — never expose a raw model page.
- **`anchor_y` ∈ [0,1]**, top-origin fraction of page height. Validate `ge=0, le=1`; clamp on the client.
- `Note` MUST be added to `db/registry.py` `REPLACED_ON_REINGEST` or `test_derived_tables_registry_covers_all_fk_models` fails and re-ingest won't wipe notes.
- Routers: thin, every route has `operation_id=`, no `sqlalchemy`/`app.db` imports (`test_routers_stay_thin_no_db_layer_imports`).
- Every backend request from the frontend goes through a new `lib/api/client.ts` helper returning `ApiResult<T>` — never raw `fetch`.
- After the backend schema change, regenerate the client (Phase 4 Step 1) before frontend typecheck, or types are stale.
- Full gate from `smv2/`: `./build.sh`. Run it in your own terminal or stop `./dev.sh` first — the `:3000` guard aborts it while a dev server is live.
- Commands' cwd is stated per step. Backend tests: `cd smv2/backend && uv run pytest`.

---

## Phase 1 — Backend: Note table, migration, registry

### Task 1: `Note` model + migration `0012_notes` + registry + cascade test

**Files:**
- Modify: `backend/app/db/models.py` (add `Note`)
- Create: `backend/app/db/migrations/versions/0012_notes.py`
- Modify: `backend/app/db/registry.py`
- Test: `backend/tests/test_notes_schema.py` (new), `backend/tests/test_course_delete_cascade.py` (extend)

**Interfaces:**
- Produces: `Note` ORM model with columns `id, course_id, section_id, surface, page, anchor_y, note_md, created_at, updated_at`; table `notes`.

- [ ] **Step 1: Write the failing schema test**

Create `backend/tests/test_notes_schema.py`:

```python
from __future__ import annotations

from app.db.engine import get_session
from app.db.models import Course, Note, Section


def test_notes_table_exists_and_persists_anchor(client):
    # client fixture runs init_db (alembic upgrade head) against the test DB.
    session = get_session()
    try:
        course = Course(id="c1", title="C", status="ready")
        section = Section(
            id="s1", course_id="c1", order_index=0, title="S",
            body_md="x", content_hash="h", extractor_version="v",
        )
        session.add_all([course, section])
        session.commit()

        note = Note(
            course_id="c1", section_id="s1", surface="pdf",
            page=2, anchor_y=0.5, note_md="hello",
        )
        session.add(note)
        session.commit()

        got = session.query(Note).one()
        assert got.course_id == "c1"
        assert got.section_id == "s1"
        assert got.surface == "pdf"
        assert got.page == 2
        assert got.anchor_y == 0.5
        assert got.note_md == "hello"
    finally:
        session.close()
```

> Note: match `Course`/`Section` required columns to their real definitions — open `backend/app/db/models.py` and copy the minimal required fields if the above constructor args drift.

- [ ] **Step 2: Run it — fails (no `Note`)**

Run: `cd smv2/backend && uv run pytest tests/test_notes_schema.py -q`
Expected: FAIL — `ImportError: cannot import name 'Note'`.

- [ ] **Step 3: Add the `Note` model**

In `backend/app/db/models.py`, after the `Highlight` class, add (mirror `Highlight`'s FK/timezone conventions):

```python
class Note(Base):
    """A free-standing margin note anchored to a vertical position on a PDF
    page (surface="pdf"), not to selected text — the coordinate equivalent of
    Highlight, for annotating a spot with no highlightable passage. anchor_y
    is a 0..1 top-origin fraction of the page height, so it survives the page
    re-rendering at any width. page is 0-based in the DB / 1-based at the API,
    same single-conversion rule as Highlight. Wiped on re-ingest (ADR-024).
    """

    __tablename__ = "notes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_new_id)
    course_id: Mapped[str] = mapped_column(
        String, ForeignKey("courses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    section_id: Mapped[str] = mapped_column(
        String, ForeignKey("sections.id", ondelete="CASCADE"), index=True, nullable=False
    )
    surface: Mapped[str] = mapped_column(String, nullable=False, default="pdf")
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    anchor_y: Mapped[float] = mapped_column(Float, nullable=False)
    note_md: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
```

Ensure `Float` is imported from sqlalchemy at the top of `models.py` (add it to the existing `from sqlalchemy import (...)` group if absent).

- [ ] **Step 4: Write the migration `0012_notes.py`**

Create `backend/app/db/migrations/versions/0012_notes.py` (structure copied from `0010_highlights.py`; `down_revision` is the current head `0011_highlight_surface`):

```python
"""notes table

Revision ID: 0012_notes
Revises: 0011_highlight_surface
Create Date: 2026-07-21

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_notes"
down_revision: Union[str, None] = "0011_highlight_surface"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notes",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("section_id", sa.String(), nullable=False),
        sa.Column("surface", sa.String(), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("anchor_y", sa.Float(), nullable=False),
        sa.Column("note_md", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["section_id"], ["sections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notes_course_id", "notes", ["course_id"])
    op.create_index("ix_notes_section_id", "notes", ["section_id"])


def downgrade() -> None:
    op.drop_index("ix_notes_section_id", table_name="notes")
    op.drop_index("ix_notes_course_id", table_name="notes")
    op.drop_table("notes")
```

Sanity-check the revision in isolation (NOT against the dev DB):
`cd smv2/backend && SMV2_DB_URL=sqlite:////tmp/notes_scratch.db uv run alembic upgrade head`
Expected: ends at `0012_notes`, no error.

- [ ] **Step 5: Register `Note` in the registry**

In `backend/app/db/registry.py`: add `Note` to the `from app.db.models import (...)` block (keep alphabetical), and add `Note,` to the `REPLACED_ON_REINGEST` list.

- [ ] **Step 6: Extend the cascade test**

In `backend/tests/test_course_delete_cascade.py::test_delete_course_cascades_to_every_fk_bearing_table`: add one `Note` row in the setup (course + section already exist there) and assert it's gone after the course delete, matching how the sibling `Highlight` row is seeded/asserted in that same test.

- [ ] **Step 7: Run backend tests — schema, cascade, architecture**

Run: `cd smv2/backend && uv run pytest tests/test_notes_schema.py tests/test_course_delete_cascade.py tests/test_architecture.py -q`
Expected: PASS — including `test_derived_tables_registry_covers_all_fk_models` (proves `Note` is registered).

- [ ] **Step 8: Commit**

```bash
git add backend/app/db/models.py backend/app/db/migrations/versions/0012_notes.py backend/app/db/registry.py backend/tests/test_notes_schema.py backend/tests/test_course_delete_cascade.py
git commit -m "feat: Note table for positional margin notes (migration 0012)"
```

---

## Phase 2 — Backend: schemas + service

### Task 2: `NoteIn/Out/UpdateIn` schemas + `notes_service`

**Files:**
- Modify: `backend/app/schemas.py`
- Create: `backend/app/services/notes_service.py`
- Test: `backend/tests/test_notes_service.py`

**Interfaces:**
- Consumes: `to_display_page` from `sections_service`.
- Produces: `notes_service.list_notes(course_id) -> list[dict]`, `create_note(course_id, *, section_id, page, anchor_y, note_md, surface) -> dict`, `update_note(note_id, fields) -> dict|None`, `delete_note(note_id) -> bool`, `InvalidSectionForCourseError`. Each dict: `id, course_id, section_id, surface, page (1-based), anchor_y, note_md, created_at, updated_at`.

- [ ] **Step 1: Write the failing service test**

Create `backend/tests/test_notes_service.py`:

```python
from __future__ import annotations

import pytest

from app.services import notes_service


def _seed_course_section(client):
    from app.db.engine import get_session
    from app.db.models import Course, Section
    session = get_session()
    try:
        session.add(Course(id="c1", title="C", status="ready"))
        session.add(Section(
            id="s1", course_id="c1", order_index=0, title="S",
            body_md="x", content_hash="h", extractor_version="v",
        ))
        session.commit()
    finally:
        session.close()


def test_create_and_list_round_trips_page_1_based(client):
    _seed_course_section(client)
    created = notes_service.create_note(
        "c1", section_id="s1", page=3, anchor_y=0.25, note_md="hi", surface="pdf",
    )
    assert created["page"] == 3          # 1-based out
    assert created["anchor_y"] == 0.25
    listed = notes_service.list_notes("c1")
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]
    assert listed[0]["page"] == 3
    assert listed[0]["note_md"] == "hi"


def test_create_rejects_section_from_other_course(client):
    _seed_course_section(client)
    with pytest.raises(notes_service.InvalidSectionForCourseError):
        notes_service.create_note(
            "c1", section_id="does-not-belong", page=1, anchor_y=0.1,
            note_md="x", surface="pdf",
        )


def test_update_and_delete(client):
    _seed_course_section(client)
    n = notes_service.create_note(
        "c1", section_id="s1", page=1, anchor_y=0.1, note_md="a", surface="pdf",
    )
    updated = notes_service.update_note(n["id"], {"note_md": "b"})
    assert updated["note_md"] == "b"
    assert notes_service.delete_note(n["id"]) is True
    assert notes_service.list_notes("c1") == []
```

- [ ] **Step 2: Run it — fails (no module)**

Run: `cd smv2/backend && uv run pytest tests/test_notes_service.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.notes_service'`.

- [ ] **Step 3: Write `notes_service.py`**

Create `backend/app/services/notes_service.py` (mirrors `highlights_service.py`; page stored `page-1`, read back via `to_display_page`):

```python
"""Positional margin notes (surface="pdf"): a note anchored to a page + a
0..1 vertical fraction (anchor_y), independent of selected text. Page crosses
1-based (API) <-> 0-based (DB) through to_display_page, the same single
conversion rule as highlights_service.
"""

from __future__ import annotations

from typing import Any

from app.db.engine import get_session
from app.db.models import Note, Section, utcnow
from app.services.sections_service import to_display_page


class InvalidSectionForCourseError(ValueError):
    pass


def _to_dict(n: Note) -> dict[str, Any]:
    return {
        "id": n.id,
        "course_id": n.course_id,
        "section_id": n.section_id,
        "surface": n.surface,
        "page": to_display_page(n.page),
        "anchor_y": n.anchor_y,
        "note_md": n.note_md,
        "created_at": n.created_at,
        "updated_at": n.updated_at,
    }


def list_notes(course_id: str) -> list[dict[str, Any]]:
    session = get_session()
    try:
        rows = (
            session.query(Note)
            .join(Section, Section.id == Note.section_id)
            .filter(Note.course_id == course_id)
            .order_by(Section.order_index, Note.created_at)
            .all()
        )
        return [_to_dict(n) for n in rows]
    finally:
        session.close()


def create_note(
    course_id: str,
    *,
    section_id: str,
    page: int,
    anchor_y: float,
    note_md: str,
    surface: str,
) -> dict[str, Any]:
    session = get_session()
    try:
        section = session.get(Section, section_id)
        if section is None or section.course_id != course_id:
            raise InvalidSectionForCourseError(
                f"section {section_id} does not belong to course {course_id}"
            )
        n = Note(
            course_id=course_id,
            section_id=section_id,
            surface=surface,
            page=page - 1,
            anchor_y=anchor_y,
            note_md=note_md,
        )
        session.add(n)
        session.commit()
        return _to_dict(n)
    finally:
        session.close()


def update_note(note_id: str, fields: dict[str, Any]) -> dict[str, Any] | None:
    session = get_session()
    try:
        n = session.get(Note, note_id)
        if n is None:
            return None
        if "note_md" in fields and fields["note_md"] is not None:
            n.note_md = fields["note_md"]
        n.updated_at = utcnow()
        session.commit()
        return _to_dict(n)
    finally:
        session.close()


def delete_note(note_id: str) -> bool:
    session = get_session()
    try:
        n = session.get(Note, note_id)
        if n is None:
            return False
        session.delete(n)
        session.commit()
        return True
    finally:
        session.close()
```

- [ ] **Step 4: Add the schemas**

In `backend/app/schemas.py`, near the Highlight schemas, add:

```python
class NoteIn(BaseModel):
    section_id: str
    page: int = Field(ge=1)
    anchor_y: float = Field(ge=0.0, le=1.0)
    note_md: str = Field(min_length=1, max_length=20000)
    surface: Literal["pdf"] = "pdf"


class NoteUpdateIn(BaseModel):
    note_md: str | None = Field(default=None, min_length=1, max_length=20000)


class NoteOut(BaseModel):
    id: str
    course_id: str
    section_id: str
    surface: Literal["pdf"]
    page: int
    anchor_y: float
    note_md: str
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 5: Run the service test — passes**

Run: `cd smv2/backend && uv run pytest tests/test_notes_service.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas.py backend/app/services/notes_service.py backend/tests/test_notes_service.py
git commit -m "feat: notes_service + NoteIn/Out schemas"
```

---

## Phase 3 — Backend: router + wiring + OpenAPI

### Task 3: `notes` router + wire into app + OpenAPI export

**Files:**
- Create: `backend/app/routers/notes.py`
- Modify: `backend/app/main.py`
- Modify: `smv2/openapi.json` (generated)
- Test: `backend/tests/test_notes_api.py`

**Interfaces:**
- Produces endpoints: `GET/POST /api/courses/{course_id}/notes`, `PATCH/DELETE /api/notes/{note_id}`, operation_ids `list_notes`/`create_note`/`update_note`/`delete_note`.

- [ ] **Step 1: Write the failing API test**

Create `backend/tests/test_notes_api.py`:

```python
from __future__ import annotations


def test_create_list_update_delete_note(client, ingest_course):
    from conftest import _first_section_id
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)

    create = client.post(
        f"/api/courses/{course_id}/notes",
        json={"section_id": section_id, "page": 2, "anchor_y": 0.4, "note_md": "hi", "surface": "pdf"},
    )
    assert create.status_code == 201
    note = create.json()
    assert note["page"] == 2
    assert note["anchor_y"] == 0.4

    listed = client.get(f"/api/courses/{course_id}/notes")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    patched = client.patch(f"/api/notes/{note['id']}", json={"note_md": "bye"})
    assert patched.status_code == 200
    assert patched.json()["note_md"] == "bye"

    deleted = client.delete(f"/api/notes/{note['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/courses/{course_id}/notes").json() == []


def test_create_note_bad_anchor_is_422(client, ingest_course):
    from conftest import _first_section_id
    course_id, *_ = ingest_course("with_bookmarks.pdf")
    section_id = _first_section_id(client, course_id)
    resp = client.post(
        f"/api/courses/{course_id}/notes",
        json={"section_id": section_id, "page": 1, "anchor_y": 1.5, "note_md": "x", "surface": "pdf"},
    )
    assert resp.status_code == 422


def test_create_note_missing_course_is_404(client):
    resp = client.post(
        "/api/courses/nope/notes",
        json={"section_id": "s", "page": 1, "anchor_y": 0.1, "note_md": "x", "surface": "pdf"},
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run it — fails (no route)**

Run: `cd smv2/backend && uv run pytest tests/test_notes_api.py -q`
Expected: FAIL — 404s / route not found.

- [ ] **Step 3: Write the router (mirror `routers/highlights.py`)**

Create `backend/app/routers/notes.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas import NoteIn, NoteOut, NoteUpdateIn
from app.services import courses_service, notes_service

router = APIRouter(prefix="/api/courses", tags=["notes"])
note_router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("/{course_id}/notes", operation_id="list_notes", response_model=list[NoteOut])
def list_notes(course_id: str) -> list[NoteOut]:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    return [NoteOut.model_validate(n) for n in notes_service.list_notes(course_id)]


@router.post(
    "/{course_id}/notes", operation_id="create_note", response_model=NoteOut, status_code=201
)
def create_note(course_id: str, body: NoteIn) -> NoteOut:
    if courses_service.get_course(course_id) is None:
        raise HTTPException(status_code=404, detail="course not found")
    try:
        result = notes_service.create_note(
            course_id,
            section_id=body.section_id,
            page=body.page,
            anchor_y=body.anchor_y,
            note_md=body.note_md,
            surface=body.surface,
        )
    except notes_service.InvalidSectionForCourseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return NoteOut.model_validate(result)


@note_router.patch("/{note_id}", operation_id="update_note", response_model=NoteOut)
def update_note(note_id: str, body: NoteUpdateIn) -> NoteOut:
    result = notes_service.update_note(note_id, body.model_dump(exclude_unset=True))
    if result is None:
        raise HTTPException(status_code=404, detail="note not found")
    return NoteOut.model_validate(result)


@note_router.delete("/{note_id}", operation_id="delete_note", status_code=204)
def delete_note(note_id: str) -> None:
    if not notes_service.delete_note(note_id):
        raise HTTPException(status_code=404, detail="note not found")
```

- [ ] **Step 4: Wire both routers into the app**

In `backend/app/main.py::create_app()`, next to the highlights includes, add:

```python
from app.routers import notes  # with the other router imports
...
app.include_router(notes.router)
app.include_router(notes.note_router)
```

(Match the exact import/include style already used for `highlights.router`/`highlights.highlight_router`.)

- [ ] **Step 5: Run the API test + architecture — passes**

Run: `cd smv2/backend && uv run pytest tests/test_notes_api.py tests/test_architecture.py -q`
Expected: PASS (incl. `test_routers_stay_thin_no_db_layer_imports`).

- [ ] **Step 6: Export OpenAPI**

Run: `cd smv2/backend && uv run python -m app.export_openapi ../openapi.json`
Expected: `smv2/openapi.json` now contains the four note operations.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/notes.py backend/app/main.py backend/tests/test_notes_api.py openapi.json
git commit -m "feat: notes CRUD endpoints"
```

---

## Phase 4 — Frontend: client + create-a-note in the gutter

### Task 4: regen client, thread notes per-page, gutter click → composer → create

**Files:**
- Modify: `frontend/lib/api/schema.d.ts` (generated), `frontend/lib/api/client.ts`
- Modify: `frontend/components/reader/PdfPagesView.tsx`, `frontend/components/reader/ReadingColumn.tsx`
- Create: `frontend/components/reader/NoteComposerPopover.tsx`
- Test: `frontend/__tests__/reader/pdf-note-create.test.tsx`

**Interfaces:**
- Consumes: `NoteOut` (generated), `listNotes/createNote/updateNote/deleteNote` (client.ts).
- Produces: per-page note pins + a create flow. `PdfPagesView` gains a `notes?: NoteOut[]` prop, filtered per page like `highlights`.

- [ ] **Step 1: Regenerate the typed client**

Run: `cd smv2/frontend && npm run gen:api`
Then confirm no hand-edit drift: `cd smv2/frontend && git diff --stat lib/api/schema.d.ts` (should show additions for the note paths).

- [ ] **Step 2: Add client helpers**

In `frontend/lib/api/client.ts`, add a `NoteOut` type export and four helpers, following the exact `request(client.<VERB>(...))` shape used by `listHighlights`/`createHighlight`/`updateHighlight`/`deleteHighlight` (copy those, swap the paths/opids). Signatures:

```ts
export type NoteOut = components["schemas"]["NoteOut"];

export function listNotes(courseId: string): Promise<ApiResult<NoteOut[]>> { /* client.GET("/api/courses/{course_id}/notes", ...) */ }
export function createNote(courseId: string, body: {
  section_id: string; page: number; anchor_y: number; note_md: string; surface: "pdf";
}): Promise<ApiResult<NoteOut>> { /* client.POST(...) */ }
export function updateNote(noteId: string, body: { note_md: string }): Promise<ApiResult<NoteOut>> { /* client.PATCH("/api/notes/{note_id}", ...) */ }
export function deleteNote(noteId: string): Promise<ApiResult<NoteOut>> { /* client.DELETE(...) — use `ok`, no body */ }
```

- [ ] **Step 3: Write the failing create test**

Create `frontend/__tests__/reader/pdf-note-create.test.tsx`, mirroring `__tests__/reader/pdf-highlight-create.test.tsx`'s setup (mock `@/lib/api/client`, render the pages surface). It must:
1. Render a PDF page (reuse the existing pdf-highlight test's pdf.js mock/harness).
2. Simulate a click on the page's note gutter (`data-testid="note-gutter-{pageNumber}"`) at a known y within a mocked wrapper rect.
3. Type into the composer and submit.
4. Assert `createNote` was called with `{ section_id, page, anchor_y, note_md, surface: "pdf" }`, `anchor_y` ≈ the clicked fraction.

Run: `cd smv2/frontend && npm test -- --run pdf-note-create`
Expected: FAIL (no gutter / composer yet).

- [ ] **Step 4: Thread notes to each page + add the gutter and composer**

In `PdfPagesView.tsx`: add `notes?: NoteOut[]` to props (default `[]`); pass each `PdfPage` its page's slice `notes.filter((n) => n.page === pageNumber)`. In `PdfPage`, inside the existing `wrapperRef` div (which is `position:relative` with the real page height), render a gutter layer beside the page:

```tsx
{/* Note gutter — absolutely positioned to the page wrapper so top:% tracks
    the page height at any width (no JS geometry). Sits to the right of the
    page; pointer-events only on the strip + pins. */}
<div
  data-testid={`note-gutter-${pageNumber}`}
  className="absolute inset-y-0 left-full ml-2 w-8 cursor-pointer"
  onClick={(e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const y = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
    onGutterClick?.(pageNumber, y, e.clientX, e.clientY);
  }}
/>
```

`onGutterClick` is a new `PdfPage`/`PdfPagesView` prop threaded up to `ReadingColumn`, which owns the composer state (mirror how `pagesPopover` state is owned in `ReadingColumn` today). On gutter click, `ReadingColumn` opens `NoteComposerPopover` anchored at the click point; on submit it calls `createNote(courseId, { section_id: section.id, page: pageNumber, anchor_y, note_md, surface: "pdf" })`, then refreshes the notes list (lift `notes` into `ReadingColumn` state fetched via `listNotes`, same way `highlights` are managed by `useHighlights`).

Create `NoteComposerPopover.tsx` by mirroring `HighlightEditPopover.tsx` (a small floating card with a textarea + Save/Cancel), using `useDismissOnOutsideOrEscape` for dismissal and `useDialogFocus` for focus — do NOT give it Escape via `useKeyboardShortcuts` (scope-stack shadowing footgun, per smv2-frontend-feature §5).

> The exact gutter width/offset and popover position are tuned against the running reader; the load-bearing logic is the `anchor_y` computation (clamped 0..1 from the live rect) and passing `page`+`surface:"pdf"`.

- [ ] **Step 5: Run the create test — passes**

Run: `cd smv2/frontend && npm test -- --run pdf-note-create`
Expected: PASS.

- [ ] **Step 6: Typecheck + commit**

Run: `cd smv2/frontend && npm run typecheck`
```bash
git add frontend/lib/api/schema.d.ts frontend/lib/api/client.ts frontend/components/reader/PdfPagesView.tsx frontend/components/reader/ReadingColumn.tsx frontend/components/reader/NoteComposerPopover.tsx frontend/__tests__/reader/pdf-note-create.test.tsx
git commit -m "feat: create margin notes from the PDF gutter"
```

---

## Phase 5 — Frontend: show / edit / delete note pins

### Task 5: render existing notes as pins, edit + delete

**Files:**
- Modify: `frontend/components/reader/PdfPagesView.tsx`, `frontend/components/reader/ReadingColumn.tsx`
- Create: `frontend/components/reader/NoteEditPopover.tsx`
- Test: `frontend/__tests__/reader/pdf-note-edit.test.tsx`

- [ ] **Step 1: Write the failing show/edit/delete test**

Create `frontend/__tests__/reader/pdf-note-edit.test.tsx`, mirroring `pdf-highlight-edit.test.tsx`:
1. Render a page with one note (`anchor_y: 0.5`) supplied via the mocked `listNotes`.
2. Assert a pin renders (`data-testid="note-pin-{id}"`) with `style.top` `"50%"`.
3. Click it → edit popover; change text → assert `updateNote(id, { note_md })`.
4. Click delete → assert `deleteNote(id)` and the pin is gone.

Run: `cd smv2/frontend && npm test -- --run pdf-note-edit`
Expected: FAIL.

- [ ] **Step 2: Render pins + wire edit/delete**

In `PdfPage`, render the page's notes inside the gutter layer:

```tsx
{pageNotes.map((n) => (
  <button
    key={n.id}
    type="button"
    data-testid={`note-pin-${n.id}`}
    style={{ top: `${n.anchor_y * 100}%` }}
    className="absolute left-0 -translate-y-1/2 ..."
    onClick={(e) => { e.stopPropagation(); onNoteClick?.(n, e.clientX, e.clientY); }}
    aria-label={`Note on page ${n.page}`}
  />
))}
```

`onNoteClick` threads up to `ReadingColumn`, which opens `NoteEditPopover` (mirror `HighlightEditPopover`: a textarea prefilled with `note_md` + Save + Delete). Save → `updateNote`; Delete → `deleteNote`; both refresh the `notes` state. `e.stopPropagation()` prevents the pin click from also triggering the gutter's create handler.

- [ ] **Step 3: Run test — passes**

Run: `cd smv2/frontend && npm test -- --run pdf-note-edit`
Expected: PASS.

- [ ] **Step 4: Typecheck + commit**

```bash
git add frontend/components/reader/PdfPagesView.tsx frontend/components/reader/ReadingColumn.tsx frontend/components/reader/NoteEditPopover.tsx frontend/__tests__/reader/pdf-note-edit.test.tsx
git commit -m "feat: show, edit, and delete margin note pins"
```

---

## Phase 6 — Frontend: NotesPanel lists standalone notes

### Task 6: merge notes into the course-wide NotesPanel

**Files:**
- Modify: `frontend/components/reader/NotesPanel.tsx`
- Test: `frontend/__tests__/annotations/notes-panel.test.tsx` (extend)

- [ ] **Step 1: Write the failing panel test**

In `frontend/__tests__/annotations/notes-panel.test.tsx`, add a case: mock `listNotes` to return one note (with `note_md` + `page`) and `listHighlights` to return one highlight; open the panel; assert BOTH the highlight's quote and the note's text render, grouped under their section, and the note row shows a "PDF p.N" badge.

Run: `cd smv2/frontend && npm test -- --run notes-panel`
Expected: FAIL (panel only fetches highlights).

- [ ] **Step 2: Fetch and merge notes**

In `NotesPanel.tsx`: alongside `listHighlights`, also `listNotes(courseId)` in the same open-effect (`Promise.all`), extend the ready state to hold both, and render standalone notes in each section group. A note row shows its `note_md` (via `Markdown`), a "PDF p.N" badge (reuse the existing badge markup), and on click calls `onNavigate(note.section_id, "pdf")`. Update the empty state to "No highlights or notes yet." Keep the "never hidden, never auto-deleted" grouping rule (a note whose section isn't found still gets a group, sorted last).

- [ ] **Step 3: Run test — passes**

Run: `cd smv2/frontend && npm test -- --run notes-panel`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/reader/NotesPanel.tsx frontend/__tests__/annotations/notes-panel.test.tsx
git commit -m "feat: list margin notes in the NotesPanel"
```

---

## Phase 7 — ADR, re-ingest warning copy, full gate

### Task 7: ADR + upload warning + gate

**Files:**
- Modify: `smv2/docs/decisions.md` (new ADR)
- Modify: the upload/re-ingest warning component (grep `frontend/` for the existing "highlights" wipe warning copy)

- [ ] **Step 1: Write the ADR**

Append a new ADR (next number after ADR-024) to `smv2/docs/decisions.md`, following the existing ADR format. Record: positional margin notes use a normalized-y anchor (not pixels/CFI/text-quote) because PDF pages render fit-to-width with fixed aspect ratio; a separate `Note` entity rather than overloading text-quote `Highlight`; PDF-surface-only and wiped-on-re-ingest for the MVP.

- [ ] **Step 2: Update the re-ingest warning copy**

Run: `cd smv2/frontend && grep -rin "highlight" --include='*.tsx' components app | grep -i "re-ingest\|re-upload\|wiped\|will be removed"` to find the existing warning. Add "and notes" to it (the warning that re-ingest deletes annotations). If no such warning exists, note it in the commit and skip (don't invent UI not in the spec).

- [ ] **Step 3: Full gate**

Run from `smv2/` (stop `./dev.sh` first — the `:3000` guard): `./build.sh`
Expected: backend pytest + OpenAPI export + frontend gen:api/typecheck/tests/build all green.

- [ ] **Step 4: Commit**

```bash
git add smv2/docs/decisions.md frontend/...  # whatever Step 2 changed
git commit -m "docs: ADR for positional margin notes; warn notes are wiped on re-ingest"
```

---

## Self-Review

**Spec coverage:**
- Normalized-y anchor + CSS `top:%` — Task 4 Step 4, Task 5 Step 2. ✓
- New `Note` table, migration, registry (REPLACED_ON_REINGEST) — Task 1. ✓
- Single page conversion via `to_display_page` — Task 2 Step 3. ✓
- Wiped on re-ingest — registry (Task 1) + cascade test; re-ingest wipe is what registry membership drives. ✓
- CRUD endpoints + OpenAPI + client — Tasks 2, 3, 4. ✓
- Gutter create / pin show / edit / delete (PDF only) — Tasks 4, 5. ✓
- NotesPanel integration — Task 6. ✓
- ADR + re-ingest warning — Task 7. ✓
- Out of scope (source notes, colors, drag, export) — nothing in the plan adds them. ✓

**Placeholder scan:** Backend steps carry complete code. Frontend Tasks 4–6 give the load-bearing code (anchor_y math, `top:%`, client helpers) in full and explicitly mirror named existing files for popover boilerplate — these are mirror-references to real files, not "TODO"s. Layout tuning (gutter width) is flagged as running-app work, not left vague in logic.

**Type consistency:** `NoteOut`/`listNotes`/`createNote`/`updateNote`/`deleteNote` used consistently between client (Task 4) and consumers (Tasks 4–6). `create_note(page)` 1-based in → stored `page-1` (Task 2 Step 3) → `to_display_page` back to 1-based, asserted in Task 2 Step 1 and Task 3 Step 1. `anchor_y` bounds `[0,1]` enforced in schema (Task 2 Step 4) and clamped client-side (Task 4 Step 4).
