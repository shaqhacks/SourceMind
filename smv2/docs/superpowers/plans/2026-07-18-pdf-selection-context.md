# PDF-Page Selection → "Add to Chat" Context Pill (Plan) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Let a student select the real text on the **PDF pages view** (not just the extracted Source view) and click **"Add to chat"** to attach that passage as context to their next question, shown as a context pill glued to the chat composer (like Cursor/Claude Code).

**Architecture:** Overlay pdf.js's `TextLayer` (v6 class API) on each `PdfPagesView` canvas so the PDF text is selectable. A selection there raises an "Add to chat"-only popover that feeds the *existing* `onExplainSelection → pendingSelection → sendChat(selection)` pipeline (Task 9 of the source-view work) — the Pages view only ever renders the active section's pages, so `section_id = section.id` with no page→chapter mapping. The current "Asking about…" chip is replaced by a composer-glued context pill (**📄 "N words — '…'"**, ×-to-remove, full text on hover) shown on both surfaces; Source view's "Explain" is renamed to "Add to chat". **No backend change** — `ChatIn.selection` already exists.

**Tech stack:** Next.js 16 (App Router) + React 19 + TS, `pdfjs-dist@6.1.200` (`TextLayer` class API — NO `renderTextLayer` in this version), Tailwind v4 + `globals.css`, Vitest + Testing Library.

## Design decisions (owner-approved 2026-07-18)

- Trigger: **explicit "Add to chat"** action (selecting to read/copy attaches nothing).
- Pill: **📄 "N words — '…snippet…'"**, × to remove, full passage on hover; glued to the composer.
- **One passage at a time** (a new add replaces); **one-shot** (clears after send). No backend change.
- PDF-view selection is **context-only and transient** — it does NOT paint or persist a highlight on the PDF (persisted PDF highlighting is a later, larger follow-up).
- Cross-text-space is expected: the PDF text-layer text ≠ Source `body_md`, so the backend's `_build_selection_block` won't find it verbatim and **degrades to sending just the quoted passage** — acceptable (existing graceful path).

## Global Constraints

- Everything under `smv2/frontend/` — never touch repo-root `frontend/` (v1).
- Frontend cwd `smv2/frontend`: tests `npm test -- --run`, `npm run typecheck`, `npm run lint`, `npm run build`. CI-trusted gate is `./build.sh` from `smv2/`.
- pdf.js is **6.1.200**: use `new TextLayer({textContentSource, container, viewport}).render()` — there is no `renderTextLayer` in this version. Build the TextLayer with the **CSS-pixel viewport** (the fit-to-width, non-DPR `viewport` matching `canvas.style.width/height`), NOT the DPR-scaled pixel buffer.
- Do NOT deep-import `pdfjs-dist/web/pdf_viewer.css` — Next App Router rejects global CSS outside the root layout. Hand-copy the minimal `.textLayer` rules into `app/globals.css`.
- No backend change; do not touch `openapi.json`/`schema.d.ts` (no regen).
- Page numbers: `section.page_start/page_end` are already 1-based inclusive per-asset — pass straight to pdf.js `doc.getPage(n)`; never +1.
- `exact` capped at 2000 chars (matches `ChatSelectionIn.exact`).
- Reuse existing hooks (`useDismissOnOutsideOrEscape`, `useDialogFocus`, `useKeyboardShortcuts`) for any popover; colors/surfaces from tokens.
- Commit messages: lowercase conventional ending with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: pdf.js text layer on the PDF pages (enable selection)

**Files:**
- Modify: `smv2/frontend/components/reader/PdfPagesView.tsx` (`PdfPage`, ~lines 131-209: the per-page render effect + wrapper DOM)
- Modify: `smv2/frontend/app/globals.css` (add minimal `.textLayer` rules)
- Test: `smv2/frontend/__tests__/reader/pdf-text-layer.test.tsx` (new — jsdom can't run pdf.js rendering; test the DOM structure/wrapper wiring with pdf.js mocked, and assert cleanup)

**Interfaces:**
- Produces: each rendered page now has a selectable `.textLayer` div overlaying its canvas, aligned to the canvas CSS box. No new exports; Task 2 relies on the text being selectable within the PagesView DOM subtree.

**Design notes (read before implementing):**
- Read `node_modules/pdfjs-dist/types/src/display/text_layer.d.ts` to confirm the `TextLayer` constructor + `render()`/`cancel()` signature for 6.1.200 before writing.
- Current `PdfPage` wrapper is `flex items-center justify-center` — the `.textLayer` needs a `position:relative` parent sized exactly to the canvas CSS box. Add an inner wrapper: `<div style={{position:"relative", width: canvas.style.width, height: canvas.style.height}}>` containing the `<canvas>` and, as a sibling, `<div className="textLayer" ref={textLayerRef}>`.
- In the same render effect that draws the canvas (gated on `nearViewport`), after computing the CSS-px `viewport` (the non-DPR one at `PdfPagesView.tsx:151`), build the text layer:
  ```ts
  const textContentSource = await page.getTextContent();
  const tl = new TextLayer({ textContentSource, container: textLayerEl, viewport });
  textLayerEl.style.setProperty("--scale-factor", String(viewport.scale));
  await tl.render();
  ```
  (pdf.js 6 positions spans in JS from `viewport.scale`; the `--scale-factor` var is what its internal `setLayerDimensions` reads — set it to `viewport.scale`.)
- Cleanup: the effect's cleanup must `tl.cancel()` and clear `textLayerEl` (`textLayerEl.replaceChildren()` / `textContent = ""`), and cancel the render task, to avoid stale spans on re-render/unmount. Same lifecycle as the existing canvas render task.
- Import: extend the existing `import { GlobalWorkerOptions, getDocument, type PDFDocumentProxy } from "pdfjs-dist";` to include `TextLayer`.
- `.textLayer` CSS in globals.css (minimal, hand-copied — spans transparent so the page looks unchanged but text is selectable):
  ```css
  .textLayer { position:absolute; inset:0; overflow:clip; opacity:1; line-height:1; text-align:initial; transform-origin:0 0; forced-color-adjust:none; z-index:0; }
  .textLayer span, .textLayer br { color:transparent; position:absolute; white-space:pre; cursor:text; transform-origin:0% 0%; }
  .textLayer span::selection { background:rgba(120,160,255,0.4); }
  .textLayer br::selection { background:transparent; }
  ```

- [ ] **Step 1: Read the installed TextLayer API**, then write the failing test: render `PdfPage` with pdf.js mocked (mock `getDocument`/page so `getTextContent` returns a couple of items and `render` resolves); assert a `.textLayer` element is created as a sibling of the canvas inside a `position:relative` wrapper, and that unmounting calls the text layer's `cancel()`. (Mock `TextLayer` to record construction + cancel.)
- [ ] **Step 2: Run** `npm test -- --run __tests__/reader/pdf-text-layer.test.tsx` → FAIL.
- [ ] **Step 3: Implement** the wrapper + text-layer render/cleanup in `PdfPage`, add the `.textLayer` CSS to `globals.css`.
- [ ] **Step 4: Run** the new test + existing `npm test -- --run __tests__/reader/*pdf*.test.tsx __tests__/**/pages*.test.tsx` (whatever PdfPagesView/PagesView tests exist) → PASS; `npm run typecheck`, `npm run lint` clean.
- [ ] **Step 5: Commit** `feat: add selectable text layer to pdf pages view`.

---

### Task 2: PDF-view selection → "Add to chat" popover

**Files:**
- Create: `smv2/frontend/components/reader/AddToChatPopover.tsx` (a minimal popover: one "Add to chat" button; reuses the dismiss/focus/shortcut hooks)
- Modify: `smv2/frontend/components/reader/ReadingColumn.tsx` (the `mode === "pages"` branch: wrap `PagesView` in a ref'd div; capture selection; render the popover)
- Test: `smv2/frontend/__tests__/reader/pdf-selection.test.tsx`

**Interfaces:**
- Consumes: the existing `onExplainSelection(sel: {sectionId, exact})` prop already on `ReadingColumn` (Task 9), and the active `section`.
- Produces: a Pages-mode selection → `onExplainSelection({ sectionId: section.id, exact })`. `AddToChatPopover` props `{ anchorRect: DOMRect; onAdd: () => void; onClose: () => void }`.

**Design notes:**
- In ReadingColumn's pages branch, wrap `<PagesView/>` in `<div ref={pagesRef} onMouseUp={handlePagesMouseUp}>`. `handlePagesMouseUp`: read `window.getSelection()`; if non-collapsed and both anchor/focus are inside `pagesRef.current`, take `const exact = sel.toString().trim().slice(0, 2000)`; if non-empty, open `AddToChatPopover` at `sel.getRangeAt(0).getBoundingClientRect()`.
- No `selectorFromRange`, no `isHighlightApiSupported()` gate — this path is plain text selection for context, independent of the CSS Custom Highlight API and of persistence.
- "Add to chat" → `onExplainSelection({ sectionId: section.id, exact })`; then `window.getSelection()?.removeAllRanges()` and close.
- `AddToChatPopover` mirrors `SelectionPopover`'s structure (fixed-position, dismiss-on-outside/escape, shortcut scope) but with a single button.
- Do not interfere with normal PDF text selection/copy when the user doesn't click "Add to chat".

- [ ] **Step 1: Write failing tests** — render ReadingColumn in `mode="pages"` with a section that has `asset_id`/pages (mock PagesView/PdfPagesView to render a simple selectable text node, or mount a stand-in). Simulate a selection in the pages container + mouseup → assert the "Add to chat" popover appears; click it → assert `onExplainSelection` fired with `{sectionId: section.id, exact}`; Escape → popover gone; a collapsed click → no popover.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement `AddToChatPopover` + the pages-branch wiring.
- [ ] **Step 4:** new test + existing ReadingColumn tests pass; typecheck + lint clean.
- [ ] **Step 5: Commit** `feat: add-to-chat from a pdf page selection`.

---

### Task 3: Composer context pill + rename Explain → "Add to chat"

**Files:**
- Modify: `smv2/frontend/components/Chat.tsx` (add an optional `composerAccessory?: React.ReactNode` prop rendered directly above the composer `<form>`)
- Modify: `smv2/frontend/components/reader/CourseChatDrawer.tsx` (replace the "Asking about…" chip with a `SelectionContextPill` passed as `composerAccessory`)
- Create: `smv2/frontend/components/reader/SelectionContextPill.tsx` (the pill: 📄 "N words — '…'", × remove, full text on hover)
- Modify: `smv2/frontend/components/reader/SelectionPopover.tsx` + `HighlightEditPopover.tsx` (rename the "Explain" button label to "Add to chat"; keep the `onExplain` prop name/wiring unchanged to avoid a wide rename)
- Test: `smv2/frontend/__tests__/reader/selection-context-pill.test.tsx`; update `course-chat-drawer.test.tsx`

**Interfaces:**
- `Chat`'s new optional prop `composerAccessory` renders above the input; absent → identical to today (no visual/behavior change for other Chat users, if any).
- `SelectionContextPill` props `{ exact: string; onRemove: () => void }`. Word count = `exact.trim().split(/\s+/).filter(Boolean).length`. Shows `📄 {n} words — "{first ~50 chars}…"`; `title={exact}` (full text on hover); an × button → `onRemove`.
- `CourseChatDrawer` passes `composerAccessory={pendingSelection ? <SelectionContextPill exact={pendingSelection.exact} onRemove={onConsumeSelection}/> : null}` and removes the old top-of-panel chip JSX.

**Design notes:**
- The `pendingSelection` lifecycle (attach on Add-to-chat, consume on successful send or ×) is unchanged from Task 9 — this task only moves/restyles its presentation and relabels the trigger.
- Keep the send path identical: no-selection sends exactly as before.

- [ ] **Step 1: Write failing tests** — `SelectionContextPill` renders the word count + truncated snippet + full-text title + working × (calls `onRemove`); `CourseChatDrawer` with a `pendingSelection` shows the pill above the composer (not the old chip), and sending still calls `sendChat` with the selection then consumes it (existing behavior); the "Explain" buttons now read "Add to chat".
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** implement the `composerAccessory` slot in Chat.tsx, the pill, the CourseChatDrawer swap, and the two button relabels.
- [ ] **Step 4:** new + updated tests pass; existing chat/reader tests green; typecheck + lint clean.
- [ ] **Step 5: Commit** `feat: composer context pill; rename explain to add-to-chat`.

---

### Task 4: Full gate + manual browser verification

- [ ] **Step 1:** (cwd `smv2/frontend`) `npm run lint`, `npm test -- --run` → all green.
- [ ] **Step 2:** (cwd `smv2/`) `./build.sh` → every stage green, no `openapi.json`/`schema.d.ts` drift (this plan touches no backend).
- [ ] **Step 3: Manual browser pass** (jsdom can't render pdf.js or compute text-layer geometry). With `./dev.sh`, open the algebra course (`html_status:"none"` → pdf.js canvas path), switch to **Pages**: confirm PDF text is selectable and the selection boxes align with the glyphs; select a passage → "Add to chat" → confirm the drawer opens with the context pill (📄 N words + snippet, × works); type a question + Send → confirm it sends (chip clears); confirm Source view's "Explain" now reads "Add to chat" and still works; confirm no console errors. Report what was observed.

---

## Out of scope
- Persisted highlights/notes painted on the PDF pages view (larger Plan-3 follow-up).
- The pdf2htmlEX HTML-iframe pages path (`html_status:"ready"`) — remains non-selectable (sandboxed iframe); documented limitation.
- Multiple stacked context passages; sticky (cross-message) context.
- Text-layer re-alignment on live window resize mid-view (canvas renders once at mount scale; a remount re-renders both — acceptable).
