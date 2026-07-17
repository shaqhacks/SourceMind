# Highlights, Notes & Explain-in-Chat — Design (smv2)

- Date: 2026-07-17
- Status: owner-approved design; no implementation yet
- Scope: SourceMind v2 only (`smv2/backend`, `smv2/frontend`)

## Goal

Students reading a course can select text, highlight it in a color, attach a
markdown note, and ask the course AI chat to explain the selected passage.
UX inspired by Readest (https://github.com/readest/readest) — reimplemented,
not copied (see Licensing).

## Research findings that shaped this design

- smv2 already renders original PDFs with pdfjs-dist
  (`components/reader/PdfPagesView.tsx`, canvas per page) and pdf2htmlEX HTML
  pages (`HtmlPagesView.tsx`, inside `<iframe sandbox="">`), selected by
  `PagesView.tsx`. Readest uses the same engine (pdfjs-dist, wrapped by
  foliate-js). There is no viewer to swap; the missing piece is the
  annotation layer.
- Licensing: readest's app/UI code (including its `Annotator.tsx`) is
  AGPL-3.0 and MUST NOT be copied into this repo — AGPL's network clause
  would extend copyleft to all of SourceMind even if only hosted. foliate-js
  is MIT and pdfjs-dist is Apache-2.0. This design uses no readest code and
  adds no foliate-js dependency.
- Readest anchors annotations with EPUB CFI (DOM-structure addressing).
  Rejected here: smv2 renders the same text in multiple distinct DOMs
  (react-markdown tree, pdf.js text layer), so anchors must be text-based,
  not structure-based.

## Owner decisions

1. **Surfaces**: both source (markdown) view and pages (PDF) view in this
   build. Lesson view excluded — `lesson_md` is different text from the
   anchored `body_md`.
2. **Re-ingest fate**: highlights are **wiped** on re-ingest
   (`REPLACED_ON_REINGEST`, like `ChatTurn`). The re-ingest UI must warn
   that highlights/notes will be lost. Upgrading later to remap-survival is
   additive, not a rewrite.
3. **Explain UX**: a scoped message into the existing course chat drawer —
   no separate explain endpoint or second LLM surface.
4. **Mechanism**: deterministic text-quote anchors + browser-native CSS
   Custom Highlight API. No new runtime dependency, no DOM mutation, no LLM
   involvement in anchoring (prime directive: deterministic before
   generative).

## Data model

New table `highlights` (`backend/app/db/models.py`):

| Column | Type | Notes |
|---|---|---|
| `id` | str, pk | random UUID — content-addressing buys nothing for wiped-on-reingest rows |
| `course_id` | FK `courses.id` | cascade delete |
| `section_id` | FK `sections.id` | cascade delete |
| `exact` | Text | verbatim selected text, ≤ 2000 chars |
| `prefix` | String(64) | context immediately before the selection |
| `suffix` | String(64) | context immediately after the selection |
| `occurrence` | int | 0-based index among matches, disambiguates repeated text |
| `page` | int, nullable | 0-based (same convention as `Section.page_start`); placement hint for pages view |
| `color` | String | enum: `yellow` (default), `green`, `blue`, `pink` |
| `note_md` | Text, nullable | a highlight without a note is valid |
| `created_at` / `updated_at` | datetime | follow existing model conventions |

- Registry: add `Highlight` to `REPLACED_ON_REINGEST` in
  `app/db/registry.py`. `test_derived_tables_registry_covers_all_fk_models`
  enforces membership; the re-ingest regression test is extended to assert
  the wipe.
- Migration: next Alembic revision under
  `backend/app/db/migrations/versions/`.
- An ADR entry goes into `smv2/docs/decisions.md` at implementation time
  (new user-data table classified as wiped + the AGPL/no-copy rationale).

## API

House pattern: Pydantic schemas (`app/schemas.py`) → service
(`app/services/highlights_service.py`) → thin router
(`app/routers/highlights.py`).

- `GET /api/courses/{course_id}/highlights` — list, ordered by section order
  then in-text position (feeds the notes panel)
- `POST /api/courses/{course_id}/highlights` — create; validates the section
  belongs to the course, `exact` non-empty and ≤ 2000 chars, color in enum
- `PATCH /api/highlights/{highlight_id}` — `note_md` (≤ 20k chars) and/or
  `color`
- `DELETE /api/highlights/{highlight_id}`

404s per house style. After backend changes:
`uv run python -m app.export_openapi ../openapi.json` then
`npm run gen:api` — generated artifacts are never hand-edited.

## Chat extension

- `ChatIn` gains optional `selection: {section_id: str, exact: str} | null`
  (`exact` ≤ 2000 chars).
- `chat_service.send_chat`: when present, verify the section, then prepend a
  clearly delimited block containing the quoted passage plus up to 1000
  chars of surrounding section text on each side, ahead of the normal RAG
  excerpts. Retrieval, citation mapping, `ChatTurn` persistence, ledger,
  limiter, and retry behavior are all unchanged.
- Frontend: the selection popover's "Explain" action opens
  `CourseChatDrawer` and sends the message with the selection attached; the
  transcript shows a quoted-passage chip on that turn.

## Frontend

New pure utility module `lib/annotations/anchors.ts` — the core of the
feature, and the most heavily tested code in it:

- `selectorFromSelection(container, selection)` →
  `{exact, prefix, suffix, occurrence}`
- `rangeForSelector(container, selector)` → DOM `Range | null`

Matching is whitespace-normalized string search; `occurrence` disambiguates
repeats. Deterministic; no fuzzy/LLM matching.

Components/hooks:

- `useHighlights(courseId, sectionId)` — load + CRUD via the generated
  client.
- `SelectionPopover` — appears on text selection inside the reading column;
  actions: color buttons, add note, explain in chat.
- Highlight rendering via the `CSS.highlights` registry, one entry per
  color; `::highlight(...)` styles in `globals.css` with dark-theme
  variants. Feature-detect `CSS.highlights`; if absent, all annotation UI is
  hidden (graceful no-op).
- `HighlightEditPopover` — clicking a highlight: edit note (markdown
  textarea), change color, delete, explain in chat.
- `NotesPanel` — course-wide list of highlights/notes with
  click-to-navigate (reuses existing `?section=` navigation).

## Pages (PDF) view

- `PdfPagesView`: add the standard pdfjs `TextLayer` (transparent,
  absolutely positioned text) over each existing canvas. Selection and
  drawing reuse `anchors.ts` and the Custom Highlight API against the text
  layer's DOM; `page` is stored on creation and bounds the anchor search.
- `PagesView` gains a manual renderer toggle (HTML ⇄ PDF). Reason: the
  preferred pdf2htmlEX view runs in `<iframe sandbox="">` — scripts
  disabled, unique origin — so the parent page cannot read selections made
  inside it. Annotation capture in that view is **out of scope**; the
  documented future path is a small script embedded in the served page HTML,
  `sandbox="allow-scripts"` (never adding `allow-same-origin`), and
  selections shuttled out via `postMessage`.
- Text-representation drift: the pdf.js text layer's text differs from
  extracted `body_md` (whitespace, hyphenation). Matching normalizes both
  sides; when an anchor created on one surface cannot be located on the
  other, the highlight is simply not drawn there — never an error, never a
  deletion.

## Known limits (accepted)

- No highlight rendering in lesson mode.
- Re-upload destroys annotations (warned in the re-ingest UI).
- Overlapping highlights allowed; a click resolves to the smallest
  containing range.
- Anchors that fail to match are listed in `NotesPanel` but not drawn, and
  are never auto-deleted.
- Browsers without the Custom Highlight API see no annotation UI.

## Testing

- Backend: highlights CRUD + validation tests; re-ingest regression extended
  to assert the wipe; chat selection-injection test with the mocked provider
  (per `smv2-testing-standards` — no network, ever).
- Frontend: dense unit tests for `anchors.ts` (round-trip, occurrence
  disambiguation, whitespace normalization, unicode); component tests for
  `SelectionPopover` and `NotesPanel`; `CSS.highlights` mocked in vitest
  (jsdom lacks it).
- Gate: `./build.sh` from `smv2/` — the only gate CI trusts.

## Build order

1. Backend: model + Alembic revision + registry + CRUD service/router +
   tests.
2. OpenAPI export + frontend client regen.
3. `anchors.ts` + its unit tests.
4. Source-mode UI: popover, highlight rendering, edit popover, notes panel.
5. Chat selection end-to-end (backend field + drawer wiring).
6. Pages mode: TextLayer, renderer toggle, page-bounded matching.

Each step lands gate-clean; the feature is "done" only when both surfaces
work.

## Out of scope

- pdf2htmlEX iframe annotation capture (future path documented above)
- Highlight styles beyond color (underline/squiggly)
- Notes in the course-export zip (natural follow-up)
- Remap-on-reingest survival (future upgrade; additive)
- Any copying of readest source code (license-prohibited)
