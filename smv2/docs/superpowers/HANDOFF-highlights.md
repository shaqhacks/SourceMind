# Handoff — smv2 highlights/notes feature (2026-07-19)

## TL;DR
Built a full annotation system for the SourceMind v2 reader over ~5 phases:
source-view highlights + notes + "explain in chat", then the same on the
**original PDF pages**, plus two infra fixes. Everything is committed on
branch **`smv2-highlights-backend`** (31 commits off `main` @ `c8606d6`),
**local only — no git remote, no PR**. Full gate (`./build.sh`) is green
(514 frontend tests, backend tests, prod build OK). Every phase was
browser-verified and passed an independent final review ("ready to merge").

## How to run / verify
- App: `cd smv2 && ./dev.sh` → backend :8000, frontend :3000. Dashboard at
  http://localhost:3000. (`dev.sh` now auto-clears a leftover prod build —
  see g014.)
- Full gate (mirrors CI): **`cd smv2 && ./build.sh`** — RUN IT FROM `smv2/`,
  not the repo root (it's `smv2/build.sh`; running from root gives exit 127).
- Sample courses in the dev DB: "Welcome to SourceMind"
  (`a66a722a-6d5a-4494-918c-6d9e27199fad`, prose) and "Beginning and
  Intermediate Algebra" (`e3a9bdb2-aa11-4ec4-add0-d5e99438dabd`, math PDF).
- Reader URL: `/course/{courseId}?section={sectionId}`. Toggle Source/Pages/
  Lesson in the top bar. Highlighting works in **Source** and **Pages**.

## What shipped (phase → key commits)
1. **Backend highlights** (`f64cdcd`..`fe58fb1`): `Highlight` table
   (text-quote anchor: exact/prefix/suffix/occurrence + page + color +
   note_md + section_id), CRUD API, `ChatIn.selection`. **ADR-024** (smv2's
   log): highlights are WIPED on re-ingest (REPLACED_ON_REINGEST); anchors
   are text-quote, not CFI; **no readest code copied (AGPL-3.0)**.
2. **Source-view UI** (`f85edda`..`3e094d0`): `anchors.ts` matcher,
   `useHighlights` hook, `useHighlightPainter` (CSS Custom Highlight API),
   SelectionPopover (colors), HighlightEditPopover (note/recolor/delete),
   NotesPanel, and "Explain"→course chat with a `selection` field.
3. **PDF-selection→chat** (`feecb4d`..`f604b1e`, plan
   `docs/superpowers/plans/2026-07-18-pdf-selection-context.md`): added a
   pdf.js **TextLayer** over each PDF page canvas so PDF text is selectable;
   "Add to chat" attaches the passage; composer context pill (📄 N words —
   snippet); renamed "Explain"→"Add to chat".
4. **CSS/dev-cache fix g012** (`dea8070`): moved `::highlight(hl-*)` rules
   out of `globals.css` into a runtime-injected `<style>`
   (`lib/annotations/highlightStyles.ts`) because Turbopack's CSS parser
   chokes on `::highlight()`.
5. **Persisted PDF highlights + notes g013** (`610f297`..`55d7d97`, plan
   `docs/superpowers/plans/2026-07-18-pdf-highlights-notes.md`): reused the
   source stack over the PDF text layer; added a **`surface`
   ("source"|"pdf")** column (migration `0011`) so the two text-spaces stay
   distinct; aggregating `usePdfHighlightPainter`; create/paint/edit/note/
   delete on the PDF; surface-aware NotesPanel with a "PDF p.N" badge.
6. **g014** (`8a3ef0a`): `dev.sh` clears a leftover production `.next`
   (detected via `.next/BUILD_ID`, which `next dev` never creates) so
   `./build.sh` then `./dev.sh` no longer 404s.

## Architecture you must know before touching this
- **Two annotation surfaces**: source (react-markdown DOM) and pdf (pdf.js
  text-layer DOM), distinguished by `Highlight.surface`. They DO NOT
  cross-map — a PDF highlight paints only in Pages view, a source highlight
  only in Source view. This is intentional (the PDF's extracted text ≠ the
  markdown body_md, esp. for math).
- **Painting** is the browser-native **CSS Custom Highlight API**
  (`CSS.highlights` + `::highlight()`), keyed `hl-<color>` — no DOM mutation.
  The `::highlight()` rules are injected at runtime (g012).
- **⚠️ THE SEAM THAT BIT US (Critical bug, fixed in `55d7d97`):**
  `CSS.highlights` is a single document-global registry. TWO painters write
  it — source `useHighlightPainter` and pages `usePdfHighlightPainter`,
  both keyed `hl-<color>`. The source painter is mounted unconditionally in
  `ReadingColumn`; when disabled (pages mode) its cleanup clears ALL
  `hl-*` names. Because React runs child layout effects before parent, on a
  pages-mode mutation the child PDF painter set ranges and the parent source
  painter cleared them → PDF paint wiped. Fix: `paintable` (fed to the
  source painter) is a **module-level stable `NO_HIGHLIGHTS` []** in
  non-source mode, so the disabled painter never re-runs to clear.
  **Rule: never let two painters write the same global registry without
  keeping the disabled one's effect deps referentially stable.**
- **Anchors** are text-quote (exact/prefix/suffix/occurrence), resolved
  against the rendered DOM text (`anchors.ts`), page-scoped for the PDF via
  `data-pdf-page` on each `.textLayer` div.
- **Aggregating painter**: one `CSS.highlights.set("hl-<color>", …)` per
  color across ALL PDF pages (per-page `.set()` would overwrite — global
  registry).

## Repo/workflow gotchas
- **v1 vs v2**: this work is entirely under `smv2/`. Repo-root
  `backend/`/`frontend/` are the OLD v1 app — don't touch them for v2 work.
  ADR numbers collide between the two logs (smv2 ADR-024 is highlights).
- Run `./build.sh` and `./dev.sh` **from `smv2/`**.
- `data/smv2.db` is the dev DB (has the two sample courses). Runtime, gitignored.
- Session artifacts (this file, per-task briefs/reports, the blow-by-blow
  ledger) live in `.superpowers/sdd/` (gitignored scratch). The full ledger
  is `.superpowers/sdd/progress.md`. Durable decisions are in the memory
  file `smv2-highlights-feature-decisions.md`.

## State to be aware of
- Working tree: only `.gitignore` shows modified — that's a PRE-EXISTING
  edit from before this session, never staged. Leave it or check with owner.
- No git remote configured → can't open a PR. Owner explicitly chose to keep
  the branch local for now.
- Known pre-existing flake: `frontend/__tests__/**/test-attempt.test.tsx`
  fails ONLY in a full-suite run (quiz keyboard-nav), passes in isolation.
  Not from this work.

## Deferred / not done (from the final reviews — all non-blocking)
- **Open a PR** (needs a git remote) — owner's call.
- Source-note click doesn't reset an active Pages mode back to Source (the
  mirror of the pdf-note→pages behavior; brief-allowed).
- Gap-click (Element-anchored) PDF selection falls back to "Add to chat"
  instead of the color popover — `resolvePdfPageSelection` uses
  `anchorNode.parentElement.closest(...)`; could branch on `nodeType===TEXT`.
- Reader view mode doesn't restore to "pages" on a full reload (pre-existing
  `useReaderView` behavior — defaults to source).
- `HtmlPagesView` (pdf2htmlEX iframe path, `html_status:"ready"`): no
  selection/highlighting — sandboxed iframe; documented limitation.
- No highlights in the course-export zip (natural follow-up).
- Remap-on-reingest survival (highlights currently WIPED on re-ingest).
- Minor: `data-text-layer-ready` attr is written but unread; a couple of
  cosmetic test-coverage gaps (see `progress.md`).

## Suggested next steps (in rough priority)
1. Owner decision: create a git remote + open the PR (or keep local).
2. If continuing the feature: highlights in course-export; the small deferred
   UX items above (view-mode-reset, gap-click, notes-panel source reset).
3. If ever adding a THIRD highlight surface or painter, re-read the
   "seam that bit us" note above first.
