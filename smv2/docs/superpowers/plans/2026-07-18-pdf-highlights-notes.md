# Persisted PDF Highlights + Notes (Plan) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** In the Pages (PDF) view, a student can select text → highlight it in a color (painted on the PDF, persisted) → click a highlight to add/edit a markdown note, recolor, delete, or add-to-chat — the same capabilities the Source view already has, now on the original PDF (equations included).

**Architecture:** Reuse the entire source-view annotation stack — `Highlight` table, `useHighlights` CRUD hook, `useHighlightPainter` (CSS Custom Highlight API), `anchors.ts` (quote selectors), `SelectionPopover`, `HighlightEditPopover`, `highlightAtPoint` — but point it at the **PDF text layer** (the transparent selectable spans g011 overlaid on each page canvas) instead of the markdown DOM. Each `PdfPage` paints its own page's highlights over its `textLayerRef`. A new `surface` column ("source" | "pdf") on `Highlight` keeps the two text-spaces distinct: PDF highlights anchor in / paint on the PDF text layer only, source highlights on the markdown only — no cross-mapping.

**Tech stack:** FastAPI + SQLAlchemy + Alembic (one column + migration) / Next.js 16 + React 19 + TS, pdfjs-dist 6.1.200 text layer, Vitest.

## Owner-approved design (2026-07-18)

- Full highlight + note + recolor + delete + add-to-chat on the PDF pages view, reusing the source-view components.
- A `surface` discriminator (source/pdf) on `Highlight`. PDF highlights paint in Pages view only; source highlights in Source view only. **No fuzzy cross-mapping** between the PDF text and the extracted markdown (unreliable).
- Notes panel lists both, labeled by surface; a PDF note navigates to its section (Pages view).
- Highlights remain wiped on re-ingest (existing).

## Global Constraints

- smv2 only; repo-root untouched. Backend cwd `smv2/backend`; frontend cwd `smv2/frontend`; gate `./build.sh` from `smv2/`.
- Schema change needs an Alembic revision (next after `0010_highlights`); `Highlight` is already in `REPLACED_ON_REINGEST` — no registry change. `test_derived_tables_registry_covers_all_fk_models` still passes (no new table).
- After backend schema change: `uv run python -m app.export_openapi ../openapi.json` then (frontend) `npm run gen:api`; commit the regenerated `openapi.json` + `schema.d.ts`.
- Page numbers: `Highlight.page` stays 0-based in DB / 1-based at the API (existing convention via `to_display_page`); a PDF highlight's page is the pdf.js 1-based page it was drawn on (converted at the service boundary like today).
- The painter works on any DOM container; the PDF text layer is per-page — resolve/paint each highlight against its own page's `.textLayer`.
- Reuse `useDismissOnOutsideOrEscape`/`useDialogFocus`/`useKeyboardShortcuts` for popovers; colors from `--highlight-*` tokens.
- Commit messages: lowercase conventional + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Backend `surface` column

**Files:**
- Modify: `smv2/backend/app/db/models.py` (`Highlight`)
- Create: `smv2/backend/app/db/migrations/versions/0011_highlight_surface.py`
- Modify: `smv2/backend/app/schemas.py` (`HighlightIn`, `HighlightOut`)
- Modify: `smv2/backend/app/services/highlights_service.py` (`create_highlight`, `_to_dict`)
- Test: `smv2/backend/tests/test_highlights.py`

**Interfaces:**
- Produces: `Highlight.surface: str` (default `"source"`), values `"source" | "pdf"`; `HighlightIn.surface: Literal["source","pdf"] = "source"`; `HighlightOut.surface`. `create_highlight(..., surface: str)`.

- [ ] **Step 1: Failing test** — extend `test_highlights.py`: create a highlight with `surface="pdf"`, assert it round-trips in the list; a create without `surface` defaults to `"source"`; an invalid surface (e.g. `"pages"`) is a 422 (Pydantic Literal).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** add `surface: Mapped[str] = mapped_column(String, nullable=False, default="source")` to `Highlight` (after `color`); Alembic `0011_highlight_surface` (`down_revision="0010_highlights"`, `op.add_column("highlights", sa.Column("surface", sa.String(), nullable=False, server_default="source"))` and drop in downgrade); add `surface: Literal["source", "pdf"] = "source"` to `HighlightIn`, `surface: Literal["source","pdf"]` to `HighlightOut`; thread through `create_highlight` and `_to_dict`.
- [ ] **Step 4:** run `uv run pytest tests/test_highlights.py tests/test_architecture.py -q` → PASS.
- [ ] **Step 5:** regen: (backend) `uv run python -m app.export_openapi ../openapi.json`; (frontend) `npm run gen:api`, `npm run typecheck`.
- [ ] **Step 6: Commit** `feat: add surface discriminator to highlights` (include regen artifacts).

---

### Task 2: `useHighlights` + client carry `surface`; painter helper for per-surface slices

**Files:**
- Modify: `smv2/frontend/lib/hooks/useHighlights.ts` (`createFromSelector` gains `surface`)
- Modify: `smv2/frontend/lib/api/client.ts` (types already regen'd; no change unless a wrapper needs it)
- Test: `smv2/frontend/__tests__/annotations/use-highlights.test.tsx`

**Interfaces:**
- Produces: `createFromSelector(sel, color, page, surface: "source" | "pdf")` — the source-view call sites pass `"source"`; Task 4 passes `"pdf"`. The returned `HighlightOut` now carries `surface`. `highlights` still holds all surfaces for the section; consumers filter.

- [ ] **Step 1:** failing test — `createFromSelector(sel, color, page, "pdf")` POSTs `surface:"pdf"` and the appended row has it. Existing calls updated to pass `"source"`.
- [ ] **Step 2–4:** fail → add the param (default `"source"` to keep the 3 existing source call sites compiling; update them to pass `"source"` explicitly) → pass. `npm run typecheck`, `npm run lint`.
- [ ] **Step 5: Commit** `feat: thread surface through useHighlights.createFromSelector`.

---

### Task 3: Paint PDF highlights on the page text layer

**Files:**
- Modify: `smv2/frontend/components/reader/PdfPagesView.tsx` (`PdfPage`, `PdfPagesView`)
- Modify: `smv2/frontend/components/reader/PagesView.tsx` (pass highlights through)
- Modify: `smv2/frontend/components/reader/ReadingColumn.tsx` (pass the section's pdf highlights into PagesView)
- Test: `smv2/frontend/__tests__/reader/pdf-highlight-paint.test.tsx`

**Interfaces:**
- Consumes: `useHighlightPainter(ref, highlights, enabled)`, `HighlightOut`, the `useHighlights` instance already in ReadingColumn.
- Produces: `PagesView`/`PdfPagesView`/`PdfPage` accept `highlights?: HighlightOut[]` (the section's `surface==="pdf"` slice); each `PdfPage` paints the highlights whose `page` equals its `pageNumber` over its `textLayerRef`, once the text layer is ready.

**Design notes:**
- **Single aggregating painter — NOT per-PdfPage.** `CSS.highlights` is document-global keyed by `hl-<color>`; if each `PdfPage` called `CSS.highlights.set("hl-green", …)` independently, the last page would overwrite the others. So paint from ONE place that aggregates ranges from all visible pages into one `Highlight` per color. Add a `usePdfHighlightPainter(pages: Array<{container: HTMLElement, highlights: HighlightOut[]}>, enabled)` (new hook alongside `useHighlightPainter`, or extend the existing one to accept a list) that, in a `useLayoutEffect`: for each page, `rangeForSelector(page.container, sel)` for each of that page's highlights (skip nulls); group ALL resolved ranges across all pages by color; `CSS.highlights.set("hl-"+color, new Highlight(...ranges))` once per color; delete empty colors; clear all four names on cleanup/disable/unsupported (same discipline as `useHighlightPainter`). The `::highlight()` background (injected at runtime by g012's `ensureHighlightStyles`) shows over the transparent text-layer spans, i.e. over the PDF glyphs. Call `ensureHighlightStyles()` here too when supported.
- **Ref collection:** `PdfPagesView` owns the aggregation. Each `PdfPage` reports its ready text-layer container + its page's highlights up to `PdfPagesView` (a callback like `onTextLayerReady(pageNumber, el)` plus an `onTextLayerGone`, or a parent-held `Map<pageNumber, HTMLElement>` populated via a ref-callback). `PdfPagesView` re-runs the painter when the set of ready containers or the highlights change. Implementer picks the cleanest collection; the invariant is ONE `CSS.highlights` entry per color across the whole pages view.
- Add a `textLayerReady` signal to `PdfPage`, set when `tl.render()` resolves (reset on re-render); only a ready container is handed to the painter (`rangeForSelector` needs the spans in the DOM).
- Add `data-pdf-page={pageNumber}` to the `.textLayer` div (Task 4/5 resolve a selection/click to its page via it).
- Per-page highlight slice: `pageHighlights = highlights.filter(h => h.page === pageNumber)` (both 1-based; `HighlightOut.page` API-1-based == pdf.js 1-based `pageNumber`).
- `ReadingColumn` computes `pdfHighlights = useMemo(() => highlights.filter(h => h.surface === "pdf" && h.section_id === section.id), [highlights, section.id])` and passes it into `PagesView` → `PdfPagesView` (pages branch only). Reuse the `isHighlightApiSupported()` gate.

- [ ] **Step 1:** failing test — render PdfPagesView (pdf.js mocked to produce a text layer with known text) with a `pdf` highlight whose `exact` is in the page text; assert `CSS.highlights.get("hl-<color>")` gets a range; a highlight for a different page/surface isn't painted; unmount clears. (Use the Task-3-of-g011 mock harness for the text layer.)
- [ ] **Step 2–4:** fail → implement the aggregating painter + ref collection + data-pdf-page + textLayerReady + ReadingColumn wiring → pass. Existing PdfPagesView tests still pass. `npm run typecheck`, `npm run lint`.
- [ ] **Step 5: Commit** `feat: paint persisted highlights on pdf pages`.

---

### Task 4: PDF selection → color highlight (create)

**Files:**
- Modify: `smv2/frontend/components/reader/ReadingColumn.tsx` (pages branch: swap `AddToChatPopover` for the full `SelectionPopover`; resolve page + container)
- Possibly remove/retire `AddToChatPopover.tsx` if fully superseded (or keep for non-supporting browsers — decide)
- Test: `smv2/frontend/__tests__/reader/pdf-highlight-create.test.tsx`

**Interfaces:**
- Consumes: `SelectionPopover` (`onColor`, `onExplain`), `selectorFromRange`, `createFromSelector(...,"pdf")`, `useHighlights`.
- Produces: selecting on the PDF and picking a color creates a `surface:"pdf"` highlight anchored in that page's text layer with the correct `page`; the painter (Task 3) paints it.

**Design notes:**
- Replace the pages-branch `AddToChatPopover` with `SelectionPopover` (colors + Add to chat) — same component the source view uses.
- On `handlePagesMouseUp`: from `window.getSelection()`, find the page container via `selection.anchorNode`'s `.closest("[data-pdf-page]")` (the `.textLayer` div, Task 3). Require anchor+focus in the SAME page container (a cross-page selection: scope to the anchor's page, or ignore — pick anchor's page for MVP). Compute `selectorFromRange(pageContainer, range)` (page-scoped occurrence) and `page = Number(pageContainer.dataset.pdfPage)`.
- `onColor(color)` → `createFromSelector(selector, color, page, "pdf")` → clear selection + close. `onExplain` → `onExplainSelection({ sectionId: section.id, exact })` (unchanged). Gate on `isHighlightApiSupported()` for the color path (paint needs it); the Add-to-chat path can stay ungated (context works without painting) — keep both behaviors, mirroring source view.

- [ ] **Step 1:** failing test — pages-mode selection over known text + mouseup shows the color popover; picking green calls `createHighlight` with `{surface:"pdf", section_id, exact, page, color:"green"}`; Add to chat still fires `onExplainSelection`.
- [ ] **Step 2–4:** fail → implement → pass; existing tests green; typecheck + lint.
- [ ] **Step 5: Commit** `feat: create highlights from a pdf selection`.

---

### Task 5: PDF click-to-edit (notes / recolor / delete)

**Files:**
- Modify: `smv2/frontend/components/reader/ReadingColumn.tsx` (pages branch: click hit-testing + `HighlightEditPopover`)
- Test: `smv2/frontend/__tests__/reader/pdf-highlight-edit.test.tsx`

**Interfaces:**
- Consumes: `highlightAtPoint`, `HighlightEditPopover`, `useHighlights.updateOne/deleteOne`.
- Produces: clicking a painted PDF highlight opens the edit popover (note textarea, recolor, delete, add-to-chat) — same as source view.

**Design notes:**
- `handlePagesClick`: when the selection is collapsed and `isHighlightApiSupported()`, find the page container under the click (`document.elementFromPoint` → closest `[data-pdf-page]`, or iterate page containers), run `highlightAtPoint(pageContainer, pagePdfHighlights, clientX, clientY)` (the page's surface="pdf" slice); open `HighlightEditPopover` for the smallest containing highlight. Wire `onSave`→`updateOne`, `onDelete`→`deleteOne`, `onExplain`→`onExplainSelection({sectionId, exact})`, `onColor`→`updateOne({color})`.
- Keep separate popover state from source-view + from the pages create-popover; don't cross-fire.

- [ ] **Step 1:** failing test — with a painted pdf highlight, a collapsed click resolving to it opens the edit popover with its note; edit+save → `updateHighlight`; recolor → `updateHighlight({color})`; delete → `deleteHighlight`; add-to-chat → `onExplainSelection`.
- [ ] **Step 2–4:** fail → implement → pass; typecheck + lint.
- [ ] **Step 5: Commit** `feat: edit and note pdf highlights`.

---

### Task 6: Notes panel surface-awareness + gate + browser verification

**Files:**
- Modify: `smv2/frontend/components/reader/NotesPanel.tsx` (label surface; navigate PDF notes to Pages view)
- Modify: `smv2/frontend/components/reader/CourseReader.tsx` if navigation needs to force pages mode for a pdf note
- Test: `smv2/frontend/__tests__/annotations/notes-panel.test.tsx`

- [ ] **Step 1:** NotesPanel test — a `surface:"pdf"` highlight renders with a PDF indicator (e.g. "PDF p.N"); clicking it navigates to the section (and, if feasible, sets pages mode). Existing source rows unchanged.
- [ ] **Step 2–4:** implement (a small surface badge + on navigate, for pdf rows, set the reader view to "pages" via the existing view hook) → pass.
- [ ] **Step 5:** `npm run lint`, `npm test -- --run`, then `./build.sh` (green, no unexpected drift), then **manual browser pass**: algebra course Pages view — select text → pick a color → confirm it paints on the PDF and survives a section switch + reload; click it → add a note, reopen; recolor; delete; add-to-chat still works; Notes panel lists the PDF highlight and navigates back to it; no console errors. Report observations.
- [ ] **Step 6: Commit** `feat: surface-aware notes panel for pdf highlights` (+ any gate fixes).

---

## Footguns (designed around)

- **Global registry collision (Task 3):** `CSS.highlights` is document-global keyed by `hl-<color>`; multiple pages must aggregate into ONE entry per color, not compete. Single aggregating painter at the PagesView level.
- **Text-layer readiness:** paint only after `tl.render()` resolves (`textLayerReady`), else `rangeForSelector` finds no spans.
- **Page resolution on select/click:** use `data-pdf-page` on the text-layer div; scope anchors per page (occurrence numbering is per-page).
- **Cross-text-space:** PDF `exact` won't match `body_md`; PDF highlights never paint in Source view (by `surface` filter) and vice versa — intended.
- **Support gate:** the color/paint path needs `isHighlightApiSupported()`; add-to-chat does not.

## Out of scope
- Cross-surface mapping (a PDF highlight appearing in Source view or vice versa).
- Highlighting on the pdf2htmlEX HTML-iframe pages path (`html_status:"ready"`) — sandboxed, unselectable; unchanged.
- Highlight styles beyond background color.
