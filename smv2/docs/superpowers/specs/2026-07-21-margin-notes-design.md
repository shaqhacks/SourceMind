# Design — margin notes in Pages view (2026-07-21)

## Goal

Let a student add a free-standing note in the **margin beside a PDF page**, at
any vertical position, without having to select and highlight text first. The
note lives in the side gutter aligned to the spot it was placed, persists, and
also appears in the course-wide NotesPanel. This removes the current wall where
a passage that can't be highlighted (see "Related" below) also can't be
annotated.

## Decisions locked in brainstorming

1. **Placement:** side gutter, **y-only**. A note anchors to a vertical
   position beside the page, not a point over the page content.
2. **Anchor:** `page` + `anchor_y`, where `anchor_y` is a **0–1 fraction of the
   page height** (top-origin). Not pixels.
3. **Data model:** a **new `Note` entity**, separate from `Highlight` (which is
   text-quote to its core and can't cleanly carry a coordinate anchor).
4. **Surface:** **PDF (Pages view) only** for the MVP.
5. **Re-ingest:** notes are **wiped on re-ingest**, same as highlights
   (ADR-024).
6. A short **ADR** records this (new anchor model / surface capability).

## Why normalized-y is the correct anchor (the crux)

Each PDF page renders fit-to-width: `scale = containerWidth / baseViewport.width`
(`components/reader/PdfPagesView.tsx:250`), drawn into a `position:relative`
wrapper whose height is the scaled page height (`PdfPage`, same file). Because a
PDF page has a fixed aspect ratio, the wrapper's height changes with column
width but the *fraction* of the way down the page does not.

So a note stored as `anchor_y ∈ [0,1]` can be rendered with a plain CSS
`top: {anchor_y * 100}%` inside that wrapper: it tracks the page's on-screen
height at any window width, on resize, with **no JavaScript geometry
measurement and no drift**. Pixel offsets would break the moment the page
re-lays-out at a new width — which is exactly why the highlight system uses
text-quote anchors instead of coordinates. Normalized-y is the coordinate
equivalent of that stability.

Markers render only once a page has actually rendered — pages are lazy
(`useNearViewport(containerRef)` in `PdfPage`), and the highlight painter
already gates on the same readiness. Notes follow that convention.

## Current state (what exists)

- `Highlight` (`backend/app/db/models.py`): text-quote anchor + `page`
  (0-based DB / 1-based API), `color`, `surface ("source"|"pdf")`, `note_md`,
  timestamps. A note today is `Highlight.note_md`, which requires `exact`
  (a selected passage) — so notes can't exist without a highlightable
  selection.
- `highlights_service` returns dicts already page-converted via
  `to_display_page` (single 0↔1 conversion point).
- Re-ingest wipes derived rows via the `db/registry.py` registry; every
  FK-bearing model must be registered (enforced by
  `tests/test_architecture.py::test_derived_tables_registry_covers_all_fk_models`)
  and is exercised by `tests/test_course_delete_cascade.py`.
- `PdfPagesView`/`PdfPage` render pages, tag each text layer with
  `data-pdf-page`, and thread a per-page-filtered `highlights` slice down.
- `NotesPanel` (`components/reader/NotesPanel.tsx`) fetches `listHighlights`
  only, groups by section, and renders each highlight + its `note_md`, with a
  "PDF p.N" badge for `surface:"pdf"`.

## Design

### Backend

**New `Note` model** (`backend/app/db/models.py`), mirroring `Highlight`'s
conventions:

| Column | Type | Notes |
|---|---|---|
| `id` | str PK | `_new_id` default |
| `course_id` | str FK → courses.id | `ondelete="CASCADE"`, indexed |
| `section_id` | str FK → sections.id | `ondelete="CASCADE"`, indexed |
| `surface` | str | default `"pdf"` (only value for MVP) |
| `page` | int | **required** for a pdf note; 0-based in DB, 1-based at API |
| `anchor_y` | float | 0–1, top-origin fraction of page height |
| `note_md` | Text | **required** (a note is its text) |
| `created_at` / `updated_at` | datetime | `utcnow` / `onupdate` |

- **Alembic migration** (next revision, e.g. `0012_notes`) creates the `notes`
  table. Schema change without a migration fails against an existing DB
  (`init_db` upgrades to head; never `create_all`).
- **Register `Note` in `db/registry.py` `REPLACED_ON_REINGEST`** — required, or
  `test_derived_tables_registry_covers_all_fk_models` fails. NOTE: registry
  membership documents intent and drives that architecture test only — it does
  NOT itself perform the wipe. The actual wipe is an explicit per-table
  `session.query(Note).filter(Note.course_id == course_id).delete()` in
  `app/pipeline/ingest.py::_run_ingest` (next to the `Highlight` line). This is
  necessary because re-ingest KEEPS unchanged sections (content-addressed ids),
  so the FK `ON DELETE CASCADE` never fires for them — only the explicit delete
  removes their notes. Guard with `test_reingest_wipes_notes`.
- **`notes_service`** (`backend/app/services/notes_service.py`): `list_notes`,
  `create_note`, `update_note`, `delete_note`, structurally parallel to
  `highlights_service`. Reuses `to_display_page` for the single page
  conversion — the export/highlights footgun (0-based leaking to the API) must
  not be reintroduced. Validates `section` belongs to `course`
  (`InvalidSectionForCourseError`) as highlights do.
- **Schemas** (`backend/app/schemas.py`): `NoteIn` (`section_id`, `page ≥ 1`,
  `anchor_y` `ge=0, le=1`, `note_md` `min_length=1`, `surface` literal
  `"pdf"`), `NoteUpdateIn` (`note_md` optional PATCH), `NoteOut` (full row,
  1-based page).
- **Router** (`backend/app/routers/notes.py`), thin, mirroring highlights:
  - `GET  /api/courses/{course_id}/notes`  → `list_notes`
  - `POST /api/courses/{course_id}/notes`  → `create_note` (201)
  - `PATCH  /api/notes/{note_id}`          → `update_note`
  - `DELETE /api/notes/{note_id}`          → `delete_note` (204)
- **OpenAPI export → `npm run gen:api`** regenerates the typed frontend client
  (`listNotes`/`createNote`/`updateNote`/`deleteNote`, `NoteOut`).

### Frontend (Pages view only)

- **Per-page notes slice:** `PdfPagesView` filters `notes` by `page` and hands
  each `PdfPage` its own page's notes, the same pattern it already uses for
  highlights.
- **Gutter layer:** inside each rendered `PdfPage`, a full-height column beside
  the page wrapper serves two jobs:
  - *Create:* a click on the gutter computes
    `anchor_y = clamp((clickClientY − wrapperTop) / wrapperHeight, 0, 1)` and
    opens a small composer; on save it calls `createNote`.
  - *Show:* existing notes render as pins positioned `top: {anchor_y*100}%`;
    clicking a pin opens a view/edit/delete popover (mirroring
    `HighlightEditPopover`: edit `note_md`, delete).
  - *Collision:* pins within a small y-threshold get a simple vertical nudge so
    they don't fully overlap (MVP; not a full layout solver).
- **NotesPanel:** also fetch `listNotes` and merge standalone notes into the
  by-section groups (a note row shows its `note_md` + a "PDF p.N" badge and,
  on click, navigates to that section in Pages view — `onNavigate` already
  takes a surface). The "No highlights yet" empty state widens to "no
  highlights or notes yet."

### Interaction / surface rules

- Notes are `surface:"pdf"`; they only appear in Pages view, exactly like pdf
  highlights (no cross-surface rendering).
- The re-ingest upload warning that currently mentions highlights being wiped
  should also mention notes (copy update).

## Out of scope (MVP)

- Source-view (markdown) margin notes — reflow makes a y-fraction meaningless.
- Note colors, drag-to-reposition, resize, cross-page notes.
- Notes in the course-export zip (the `highlights.json` export added
  2026-07-20 covers only highlights) — natural follow-up.
- The highlight-resolver fix for gap/table selections (see Related) — tracked
  separately.

## Testing

**Backend** (`backend/tests/`):
- Fresh-DB migration creates `notes`; `init_db` upgrades cleanly.
- `notes_service` CRUD + **page round-trip** (create with `page: 3` stores
  `2`, reads back `3`) + `anchor_y` persists; invalid section → 422.
- Router endpoints (list/create/patch/delete, 404s, 201/204 codes).
- **Cascade:** deleting a course and deleting a section each remove its notes
  (extend `test_course_delete_cascade.py`).
- **Re-ingest wipes notes** (registry membership + a re-ingest test), and
  `test_derived_tables_registry_covers_all_fk_models` stays green.

**Frontend** (`frontend/__tests__/`, following `smv2-testing-standards` and the
existing `pdf-highlight-*` tests):
- Clicking the gutter opens the composer and creates a note at the computed
  `anchor_y`.
- A note renders as a pin at `top: {anchor_y*100}%`.
- Edit updates `note_md`; delete removes the pin.
- `NotesPanel` lists standalone notes alongside highlights.

**Gate:** full `./build.sh` from `smv2/` (backend pytest + frontend
typecheck/tests/build). Run it in your own terminal or stop the dev server
first — the new `:3000` guard will refuse to run while a dev server is live.

## ADR

Write a new ADR (next number in the smv2 log; ADR-024 is highlights). It
records: positional margin notes use a normalized-y anchor (not pixels, not
CFI, not text-quote) because PDF pages render fit-to-width with a fixed aspect
ratio; a separate `Note` entity rather than overloading text-quote `Highlight`;
PDF-surface-only and wiped-on-re-ingest for the MVP.

## Risks / footgun review

- **Page 0↔1-based** — mitigated by routing every read through
  `to_display_page` in `notes_service` (never a raw model page in the API/UI).
- **Re-ingest wipe is two separate obligations** — (1) register in
  `REPLACED_ON_REINGEST` (satisfies the architecture test), AND (2) add the
  explicit `Note` delete to `_run_ingest`'s wipe block. Doing only (1) passes
  the gate but silently leaves notes on unchanged sections after re-ingest
  (FK cascade doesn't fire for kept sections). Both are required.
- **Lazy pages** — a note's pin can only be placed once its page wrapper has a
  real height; gate marker rendering on page-rendered state (existing pattern),
  and reserve gutter height so pins don't jump.
- **Collision density** — many notes at similar y is a real UI problem; MVP
  uses a simple nudge and accepts imperfect stacking, not a full solver.
- **anchor_y from a stale wrapper height** — compute `anchor_y` from the live
  wrapper rect at click time, and always clamp to [0,1] so a click in reserved
  padding can't store an out-of-range value.

## Related

The original trigger ("sometimes it only says Add to chat instead of letting me
highlight") is a *different* limitation: `resolvePdfPageSelection`
(`lib/annotations/anchors.ts:129`) finds the page via
`anchorNode.parentElement.closest("[data-pdf-page]")`, which assumes the
selection's anchor is a text node. A selection that starts/ends in a gap
between pdf.js spans (common around tables/math) is Element-anchored, so the
page lookup fails and only "Add to chat" is offered. Positional margin notes
sidestep this entirely (no text anchor needed); fixing the resolver so those
selections *highlight* is tracked as a separate small change.
