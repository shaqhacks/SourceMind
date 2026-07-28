"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent, type RefObject } from "react";
import Link from "next/link";

import ErrorBanner from "@/components/ErrorBanner";
import Markdown from "@/components/Markdown";
import {
  rangeForSelector,
  resolvePdfPageSelection,
  selectorFromRange,
  type QuoteSelector,
} from "@/lib/annotations/anchors";
import { highlightAtPoint } from "@/lib/annotations/hitTest";
import { isHighlightApiSupported, useHighlightPainter } from "@/lib/annotations/useHighlightPainter";
import type { HighlightOut, HighlightUpdateIn, NoteOut } from "@/lib/api/client";
import { useHighlights, type HighlightColor } from "@/lib/hooks/useHighlights";
import { useNotes } from "@/lib/hooks/useNotes";
import { prefsToCssVars, type TypographyPrefs } from "@/lib/hooks/useTypographyPrefs";
import type { ReaderSection, SectionBodyState, ViewMode } from "@/lib/reader/types";

import AddToChatPopover from "./AddToChatPopover";
import CardsCTA from "./CardsCTA";
import HighlightEditPopover from "./HighlightEditPopover";
import LessonPane, { type LessonDisplayStatus } from "./LessonPane";
import NotePopover from "./NotePopover";
import PagesView from "./PagesView";
import type { NoteClickHandler, NoteGutterClick } from "./PdfPagesView";
import SectionCards from "./SectionCards";
import SelectionPopover from "./SelectionPopover";

/** What "Explain" bubbles up to CourseReader — a plain in-process payload
 * (not a wire body), so camelCase matches this codebase's other
 * frontend-internal selection shapes (e.g. Chat's `ChatCitation`) rather
 * than the snake_case `HighlightIn` API-request convention. */
export interface ExplainSelection {
  sectionId: string;
  exact: string;
}

export interface ReadingColumnProps {
  courseId: string;
  section: ReaderSection;
  mode: ViewMode;
  typography: TypographyPrefs;
  headingRef: RefObject<HTMLHeadingElement | null>;
  columnRef: RefObject<HTMLDivElement | null>;
  body: SectionBodyState;
  onLessonStatusChange: (sectionId: string, status: LessonDisplayStatus) => void;
  onNext: () => void;
  onPrevious: () => void;
  /** The next/previous content section's title, or null when there isn't
   * one — the matching chevron isn't rendered at all in that case (the
   * mdBook-style edge behavior: no dead click zone at the first/last
   * chapter, matching the existing clamp-instead-of-wrap keyboard nav). */
  nextTitle: string | null;
  previousTitle: string | null;
  /** Fired when the user picks "Explain" on a live text selection — the
   * caller (CourseReader) owns what that means (opens chat, in Task 6). */
  onExplainSelection: (sel: ExplainSelection) => void;
}

type OpenSelectionPopover = { selector: QuoteSelector; anchorRect: DOMRect };

function pageRange(section: ReaderSection): string | null {
  if (section.page_start === null || section.page_end === null) return null;
  return `p.${section.page_start}–${section.page_end}`;
}

const NON_CONTENT_BANNER_TEXT: Record<"practice" | "answers", string> = {
  practice: "This is practice material, not regular reading — it belongs on the chapter test page.",
  answers: "This is an answer key, not regular reading — it belongs on the chapter test page.",
};

// Prev/next moved out of the old full-height edge hit-zones into a footer
// row under the body, per the redesign (ghost links split left/right over a
// top hairline). The aria-labels are unchanged — they are the reader's
// navigation contract, and the visible chapter title is now the label's
// tail rather than a bare chevron.
const NAV_LINK_CLASSES =
  "max-w-[48%] truncate rounded-md px-2 py-1 text-sm font-medium text-accent transition-colors hover:bg-accent/10 active:bg-accent/[0.18]";

// A single stable (never-reallocated) empty array, shared by every non-source
// render of `paintable` below. `useHighlightPainter`'s effect is keyed on
// `paintable`'s own reference — in pages/lesson mode it's permanently
// `enabled=false`, but `highlights.filter(...)` would still hand it a FRESH
// array on every `highlights` change (any pdf-highlight create/update/
// delete), re-running its disabled branch and calling
// `clearHighlightRegistry()` — which deletes ALL FOUR `hl-*` registry
// names, including whatever `usePdfHighlightPainter` (a descendant, whose
// layout effect commits first) just painted in the very same commit.
// Handing back this same constant instead means the disabled branch's
// deps never change outside an actual mode switch, so it clears once (on
// entering pages mode, correctly discarding a stale source paint) and then
// leaves the PDF painter's own registry entries alone.
const NO_HIGHLIGHTS: HighlightOut[] = [];

// A zero-size viewport-relative rect at a click point, for anchoring the
// note popovers the same way the highlight popovers anchor to a range's
// getBoundingClientRect (same fallback shape handleArticleClick already uses).
function pointRect(clientX: number, clientY: number): DOMRect {
  return {
    top: clientY,
    bottom: clientY,
    left: clientX,
    right: clientX,
    width: 0,
    height: 0,
  } as DOMRect;
}

export default function ReadingColumn({
  courseId,
  section,
  mode,
  typography,
  headingRef,
  columnRef,
  body,
  onLessonStatusChange,
  onNext,
  onPrevious,
  nextTitle,
  previousTitle,
  onExplainSelection,
}: ReadingColumnProps) {
  const pages = pageRange(section);

  // Mounted unconditionally (not gated on mode) so switching INTO source
  // view shows correct highlights immediately, without waiting on a fresh
  // fetch that a mode switch alone wouldn't trigger.
  const { highlights, error, createFromSelector, updateOne, deleteOne } = useHighlights(courseId, section.id);
  // Positional margin notes for this section (surface:"pdf"), independent of
  // highlights — see useNotes. Mounted unconditionally for the same reason as
  // useHighlights: switching INTO pages view shows notes immediately.
  const {
    notes,
    error: notesError,
    createNote,
    updateNote,
    deleteNote,
  } = useNotes(courseId, section.id);
  // useHighlights re-syncs its `highlights` array ASYNCHRONOUSLY (only once
  // its course-wide fetch for the new section resolves), but `body.kind`
  // can flip to "ready" for the new section before that fetch lands. In
  // that window `highlights` can still hold the PREVIOUS section's rows.
  // `section.id` is a plain prop with no such lag, so filtering on it here
  // drops stale rows (whose `section_id` won't match) until the correct
  // fetch catches up — closing the race without touching useHighlights or
  // the painter itself. rangeForSelector matches by exact text + occurrence
  // only (no section_id check), so leaving stale rows in would let a phrase
  // that also appears in the new section's text get painted as a highlight
  // that doesn't belong there.
  //
  // Also filtered to `surface === "source"` — symmetric with `pdfHighlights`
  // below, which filters `surface === "pdf"`. Without this, a `surface:
  // "pdf"` highlight whose `exact` also happens to occur in this section's
  // extracted Markdown would paint (and be click-editable) here too, in the
  // wrong view, anchored against the wrong text.
  //
  // In any mode OTHER than "source" this is the shared `NO_HIGHLIGHTS`
  // constant, not a fresh `.filter()` result — see its module-level comment
  // for why that reference stability is load-bearing, not cosmetic.
  const paintable = useMemo(
    () =>
      mode === "source"
        ? highlights.filter(
            (highlight) => highlight.surface === "source" && highlight.section_id === section.id,
          )
        : NO_HIGHLIGHTS,
    [mode, highlights, section.id],
  );
  // Pages-mode's own slice, handed to PagesView -> PdfPagesView's
  // aggregating painter: `surface === "pdf"` (a source-mode highlight's
  // selector is anchored against the rendered Markdown, not the PDF's raw
  // glyphs — painting it here would resolve against the wrong text
  // entirely) filtered to this section, same stale-row rationale as
  // `paintable` above.
  const pdfHighlights = useMemo(
    () => highlights.filter((highlight) => highlight.surface === "pdf" && highlight.section_id === section.id),
    [highlights, section.id],
  );
  const articleBodyRef = useRef<HTMLDivElement>(null);
  // Gated on body readiness, not just `mode === "source"`: the wrapper div
  // below only exists in the DOM once body.kind is "ready" (loading/error
  // render something else entirely), and a ref's `.current` mutating from
  // null to a node does NOT by itself re-trigger a dependency-array effect.
  // Tying `enabled` to body.kind flips it false -> true exactly when the
  // container (and its text) newly exists, which is what actually needs to
  // retrigger the painter.
  useHighlightPainter(articleBodyRef, paintable, mode === "source" && body.kind === "ready");

  // The live text-selection popover (create-highlight / explain). Only
  // ever set from `handleArticleMouseUp` below, which already gates on
  // source mode + a resolved body via `articleBodyRef` only existing in
  // that branch — no separate `mode`/`body.kind` check needed here.
  const [selectionPopover, setSelectionPopover] = useState<OpenSelectionPopover | null>(null);

  const closeSelectionPopover = useCallback(() => setSelectionPopover(null), []);

  // Scoped to the article wrapper via React's onMouseUp (fires on any
  // mouseup that bubbles from a descendant of that div — the wrapper only
  // exists in the DOM in the mode==="source" && body.kind==="ready"
  // branch, so this can never observe pages/lesson-mode content). A plain
  // click (no drag) collapses the selection, so this is a no-op then —
  // dismissing an already-open popover on an unrelated click is handled
  // separately by SelectionPopover's own useDismissOnOutsideOrEscape.
  //
  // Also bails when the CSS Custom Highlight API isn't supported (older
  // Safari/Firefox): opening the popover there would let a user pick a
  // color, POST a highlight row via createFromSelector, and then never see
  // it painted (useHighlightPainter's own `supported` gate makes painting
  // a no-op) — the selection would just vanish with nothing to show for
  // it. Bailing here instead means selecting text on an unsupported
  // browser is a genuine no-op: normal copy/selection still works, no
  // annotation UI appears at all.
  const handleArticleMouseUp = useCallback(() => {
    if (!isHighlightApiSupported()) return;
    const container = articleBodyRef.current;
    if (!container) return;
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return;
    const range = selection.getRangeAt(0);
    if (range.collapsed) return;
    if (!container.contains(range.startContainer) || !container.contains(range.endContainer)) {
      return;
    }
    const selector = selectorFromRange(container, range);
    if (!selector) return;
    setSelectionPopover({ selector, anchorRect: range.getBoundingClientRect() });
  }, []);

  const handleSelectionColor = useCallback(
    (color: HighlightColor) => {
      if (!selectionPopover) return;
      // Fire-and-forget: useHighlights.createFromSelector sets its own
      // `error` state on failure, which this component renders via
      // ErrorBanner below — nothing here needs to await the result. The
      // painter repaints from that hook's state automatically once the row
      // lands.
      void createFromSelector(selectionPopover.selector, color, section.page_start ?? null, "source");
      window.getSelection()?.removeAllRanges();
      setSelectionPopover(null);
    },
    [selectionPopover, createFromSelector, section.page_start],
  );

  const handleSelectionExplain = useCallback(() => {
    if (!selectionPopover) return;
    onExplainSelection({ sectionId: section.id, exact: selectionPopover.selector.exact });
    window.getSelection()?.removeAllRanges();
    setSelectionPopover(null);
  }, [selectionPopover, onExplainSelection, section.id]);

  // The edit popover for an EXISTING (already-painted) highlight, opened by
  // clicking it — as opposed to `selectionPopover` above, which is for
  // CREATING a new one from a live drag-selection. The two are mutually
  // exclusive by construction: `handleArticleClick` below only ever hit-
  // tests when the click's own selection is collapsed (see its comment),
  // which is never true for the mouseup that opens `selectionPopover`.
  const [editPopover, setEditPopover] = useState<{ highlight: HighlightOut; anchorRect: DOMRect } | null>(
    null,
  );

  const closeEditPopover = useCallback(() => setEditPopover(null), []);

  // Scoped to the article wrapper via React's onClick (same bubble-scoping
  // rationale as handleArticleMouseUp above). Fires AFTER mouseup, so by
  // the time this runs, a just-completed drag-selection (which
  // handleArticleMouseUp already turned into `selectionPopover`) is still
  // reflected in `window.getSelection()` — checking it's collapsed here is
  // what keeps a click that ends a drag-select from ALSO opening the edit
  // popover underneath/instead of the selection popover. A plain click
  // (no drag) always leaves the selection collapsed, so it falls through
  // to the hit-test.
  //
  // Bails on the same CSS Custom Highlight API support check as the
  // create-selection path: on an unsupported browser nothing is ever
  // painted (useHighlightPainter's own gate), so there is nothing a click
  // could be hit-testing against.
  const handleArticleClick = useCallback(
    (event: MouseEvent<HTMLDivElement>) => {
      if (!isHighlightApiSupported()) return;
      const container = articleBodyRef.current;
      if (!container) return;
      const selection = window.getSelection();
      if (selection && !selection.isCollapsed) return;

      const hit = highlightAtPoint(container, paintable, event.clientX, event.clientY);
      if (!hit) return;

      // Re-resolve the hit highlight's own range for its bounding rect
      // (the anchor SelectionPopover-style popovers use) — highlightAtPoint
      // only returns the highlight itself, not the Range it matched
      // against, so this is a second (cheap, single-highlight) resolve
      // rather than widening that function's return type for one caller.
      const range = rangeForSelector(container, {
        exact: hit.exact,
        prefix: hit.prefix,
        suffix: hit.suffix,
        occurrence: hit.occurrence,
      });
      const anchorRect: DOMRect = range
        ? range.getBoundingClientRect()
        : pointRect(event.clientX, event.clientY);
      setEditPopover({ highlight: hit, anchorRect });
    },
    [paintable],
  );

  const handleEditSave = useCallback(
    (patch: HighlightUpdateIn) => {
      if (!editPopover) return;
      // Fire-and-forget, same convention as handleSelectionColor above:
      // updateOne's failure surfaces through useHighlights' own `error`
      // state, rendered via ErrorBanner below, and the painter repaints
      // automatically once state settles.
      void updateOne(editPopover.highlight.id, patch);
      setEditPopover(null);
    },
    [editPopover, updateOne],
  );

  const handleEditDelete = useCallback(() => {
    if (!editPopover) return;
    void deleteOne(editPopover.highlight.id);
    setEditPopover(null);
  }, [editPopover, deleteOne]);

  const handleEditExplain = useCallback(() => {
    if (!editPopover) return;
    onExplainSelection({ sectionId: section.id, exact: editPopover.highlight.exact });
    setEditPopover(null);
  }, [editPopover, onExplainSelection, section.id]);

  // Pages-mode ("original PDF/HTML pages") selection -> color highlight
  // (surface:"pdf") or "Add to chat". Deliberately separate state/ref from
  // selectionPopover/articleBodyRef above — the two popovers must never
  // interact, since they belong to mutually exclusive view modes (only one
  // of the two wrapper divs is ever in the DOM at a time). Unlike before
  // this task, this DOES now touch the CSS Custom Highlight API and
  // selectorFromRange anchoring for the color path: `selector`/`page` are
  // null whenever a `surface:"pdf"` highlight can't be created for this
  // selection (API unsupported, no `[data-pdf-page]` ancestor — e.g.
  // HtmlPagesView's pdf2htmlEX-enhanced view doesn't tag one yet — or a
  // cross-page selection), in which case the render below falls back to
  // the exact-only AddToChatPopover, so Add to chat keeps working
  // regardless of whether painting is possible.
  const pagesRef = useRef<HTMLDivElement>(null);
  const [pagesPopover, setPagesPopover] = useState<{
    anchorRect: DOMRect;
    exact: string;
    selector: QuoteSelector | null;
    page: number | null;
  } | null>(null);

  const closePagesPopover = useCallback(() => setPagesPopover(null), []);

  // Scoped to the pages wrapper via React's onMouseUp, same bubble-scoping
  // convention as handleArticleMouseUp — the wrapper only exists in the
  // DOM in the mode==="pages" branch (and only once the section has
  // original pages), so this can never observe source/lesson content.
  const handlePagesMouseUp = useCallback(() => {
    const container = pagesRef.current;
    if (!container) return;
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      setPagesPopover(null);
      return;
    }
    // Guards against a stale/foreign selection this mouseup isn't actually
    // about (mirrors handleArticleMouseUp's identical containment check).
    if (!container.contains(selection.anchorNode) || !container.contains(selection.focusNode)) {
      return;
    }
    const exact = selection.toString().replace(/\s+/g, " ").trim().slice(0, 2000);
    if (!exact) {
      setPagesPopover(null);
      return;
    }
    const range = selection.getRangeAt(0);
    // Page-scoped anchor for a `surface:"pdf"` highlight, attempted only
    // when the CSS Custom Highlight API is supported — painting needs it,
    // and an unsupported browser gets the Add-to-chat-only fallback below
    // regardless, so resolving it would be wasted work (mirrors
    // handleArticleMouseUp's own early bail on the same check).
    const pdfAnchor = isHighlightApiSupported()
      ? resolvePdfPageSelection(selection.anchorNode, selection.focusNode, range)
      : null;
    // Also dismiss any open note popover — mirrors handleNoteGutterClick/
    // handleNoteClick dismissing the pages popovers on the reverse path, so
    // opening a highlight-selection popover can't leave a note composer/
    // editor open alongside it.
    setNoteComposer(null);
    setNoteEditPopover(null);
    setPagesPopover({
      anchorRect: range.getBoundingClientRect(),
      exact,
      selector: pdfAnchor?.selector ?? null,
      page: pdfAnchor?.page ?? null,
    });
  }, []);

  const handlePagesColor = useCallback(
    (color: HighlightColor) => {
      if (!pagesPopover?.selector || pagesPopover.page === null) return;
      // Fire-and-forget, same convention as handleSelectionColor above.
      void createFromSelector(pagesPopover.selector, color, pagesPopover.page, "pdf");
      window.getSelection()?.removeAllRanges();
      setPagesPopover(null);
    },
    [pagesPopover, createFromSelector],
  );

  const handlePagesAdd = useCallback(() => {
    if (!pagesPopover) return;
    onExplainSelection({ sectionId: section.id, exact: pagesPopover.exact });
    window.getSelection()?.removeAllRanges();
    setPagesPopover(null);
  }, [pagesPopover, onExplainSelection, section.id]);

  // The edit popover for an EXISTING (already-painted) pdf highlight,
  // opened by clicking it — mirrors `editPopover` above for the source-view
  // branch, but deliberately separate state: the two view modes render
  // mutually exclusive DOM subtrees (only one wrapper div is ever mounted
  // at a time), so there is never a reason for one branch's click to
  // resolve against the other's popover. Also kept separate from
  // `pagesPopover` (the DRAG-to-create popover for a live selection) for
  // the same reason handleArticleClick/editPopover stay separate from
  // handleArticleMouseUp/selectionPopover in the source branch:
  // `handlePagesClick` below only ever hit-tests when the click's own
  // selection is collapsed, which is never true for the mouseup that opens
  // `pagesPopover`.
  const [pagesEditPopover, setPagesEditPopover] = useState<{
    highlight: HighlightOut;
    anchorRect: DOMRect;
  } | null>(null);

  const closePagesEditPopover = useCallback(() => setPagesEditPopover(null), []);

  // Scoped to the pages wrapper via React's onClick, same bubble-scoping
  // and collapsed-selection-only convention as handleArticleClick above (a
  // click that ends handlePagesMouseUp's drag-to-create flow leaves a
  // non-collapsed selection, so it falls through here without ever
  // reaching the hit-test).
  //
  // Unlike the source view's single article container, pages mode can
  // render MULTIPLE `[data-pdf-page]` containers at once (one per rendered
  // PDF page) — so the click's own point, not a fixed ref, decides which
  // page's highlights to hit-test against. `document.elementFromPoint`
  // finds whatever DOM node is actually under the cursor; its nearest
  // `[data-pdf-page]` ancestor is that page's text-layer container (the
  // same tagging PdfPage/resolvePdfPageSelection already rely on). No
  // container under the point means the click landed outside any rendered
  // page (e.g. the "Page N" placeholder shown before a page scrolls near
  // viewport), so there's nothing to hit-test.
  const handlePagesClick = useCallback(
    (event: MouseEvent<HTMLDivElement>) => {
      if (!isHighlightApiSupported()) return;
      const selection = window.getSelection();
      if (selection && !selection.isCollapsed) return;

      const pageEl = (document.elementFromPoint(event.clientX, event.clientY) as Element | null)?.closest(
        "[data-pdf-page]",
      ) as HTMLElement | null;
      if (!pageEl) return;

      const page = Number(pageEl.dataset.pdfPage);
      if (!Number.isFinite(page)) return;

      // The page's own slice of pdfHighlights — same surface:"pdf" +
      // section scoping as `pdfHighlights` itself, narrowed further to
      // just this page so a highlight painted on a different page never
      // wins the hit-test here.
      const pageHighlights = pdfHighlights.filter((highlight) => highlight.page === page);
      const hit = highlightAtPoint(pageEl, pageHighlights, event.clientX, event.clientY);
      if (!hit) return;

      // Re-resolve the hit highlight's own range for its bounding rect,
      // same convention as handleArticleClick above.
      const range = rangeForSelector(pageEl, {
        exact: hit.exact,
        prefix: hit.prefix,
        suffix: hit.suffix,
        occurrence: hit.occurrence,
      });
      const anchorRect: DOMRect = range
        ? range.getBoundingClientRect()
        : pointRect(event.clientX, event.clientY);
      // Also dismiss any open note popover, same rationale as
      // handlePagesMouseUp above.
      setNoteComposer(null);
      setNoteEditPopover(null);
      setPagesEditPopover({ highlight: hit, anchorRect });
    },
    [pdfHighlights],
  );

  const handlePagesEditSave = useCallback(
    (patch: HighlightUpdateIn) => {
      if (!pagesEditPopover) return;
      // Fire-and-forget, same convention as handleEditSave above.
      void updateOne(pagesEditPopover.highlight.id, patch);
      setPagesEditPopover(null);
    },
    [pagesEditPopover, updateOne],
  );

  const handlePagesEditDelete = useCallback(() => {
    if (!pagesEditPopover) return;
    void deleteOne(pagesEditPopover.highlight.id);
    setPagesEditPopover(null);
  }, [pagesEditPopover, deleteOne]);

  const handlePagesEditExplain = useCallback(() => {
    if (!pagesEditPopover) return;
    onExplainSelection({
      sectionId: pagesEditPopover.highlight.section_id,
      exact: pagesEditPopover.highlight.exact,
    });
    setPagesEditPopover(null);
  }, [pagesEditPopover, onExplainSelection]);

  // Positional margin notes (Pages view). `noteComposer` = create at a gutter
  // click; `noteEditPopover` = click an existing pin to edit/delete. Kept as
  // separate state and rendered as plain sibling popovers, same convention as
  // the highlight popovers above. Opening one closes the other so two note
  // popovers are never open at once.
  const [noteComposer, setNoteComposer] = useState<{
    page: number;
    anchorY: number;
    anchorRect: DOMRect;
  } | null>(null);
  const [noteEditPopover, setNoteEditPopover] = useState<{
    note: NoteOut;
    anchorRect: DOMRect;
  } | null>(null);

  const closeNoteComposer = useCallback(() => setNoteComposer(null), []);
  const closeNoteEditPopover = useCallback(() => setNoteEditPopover(null), []);

  // A section switch (chapter nav, keyboard j/k, a "Re-read" deep link)
  // remounts both the source article wrapper and the pages wrapper (both
  // keyed on section.id above), which would otherwise leave any of these
  // six popovers anchored to a DOMRect/highlight/note from a subtree that
  // no longer exists. Closes all of them across both view modes whenever
  // the section changes, rather than relying on each view's own dismiss
  // handlers (which only fire on user interaction within that view).
  useEffect(() => {
    setSelectionPopover(null);
    setEditPopover(null);
    setPagesPopover(null);
    setPagesEditPopover(null);
    setNoteComposer(null);
    setNoteEditPopover(null);
  }, [section.id]);

  const handleNoteGutterClick = useCallback<NoteGutterClick>((page, anchorY, clientX, clientY) => {
    // Also dismiss any open highlight popover: a gutter click's mouseup can
    // bubble to handlePagesMouseUp and (re)open pagesPopover off a stale
    // selection, which would otherwise sit alongside this composer.
    setPagesPopover(null);
    setPagesEditPopover(null);
    setNoteEditPopover(null);
    setNoteComposer({ page, anchorY, anchorRect: pointRect(clientX, clientY) });
  }, []);

  const handleNoteClick = useCallback<NoteClickHandler>((note, clientX, clientY) => {
    setPagesPopover(null);
    setPagesEditPopover(null);
    setNoteComposer(null);
    setNoteEditPopover({ note, anchorRect: pointRect(clientX, clientY) });
  }, []);

  const handleNoteComposerSave = useCallback(
    (noteMd: string) => {
      if (!noteComposer) return;
      // Fire-and-forget, same convention as handleSelectionColor: useNotes
      // sets its own `error` (rendered below) on failure.
      void createNote(noteComposer.page, noteComposer.anchorY, noteMd);
      setNoteComposer(null);
    },
    [noteComposer, createNote],
  );

  const handleNoteEditSave = useCallback(
    (noteMd: string) => {
      if (!noteEditPopover) return;
      void updateNote(noteEditPopover.note.id, noteMd);
      setNoteEditPopover(null);
    },
    [noteEditPopover, updateNote],
  );

  const handleNoteEditDelete = useCallback(() => {
    if (!noteEditPopover) return;
    void deleteNote(noteEditPopover.note.id);
    setNoteEditPopover(null);
  }, [noteEditPopover, deleteNote]);

  return (
    <div className="relative flex min-h-0 flex-1">
      <div
        ref={columnRef}
        data-testid="reading-column"
        className="reading-column min-h-0 flex-1 overflow-y-auto"
        style={prefsToCssVars(typography)}
      >
        <article className="reading-measure mx-auto px-8 py-11">
          {/* Surfaces a failed highlight create/update/delete — useHighlights
              sets `error` to a human string (via describeError) on any of
              those, and clears it again once a later mutation succeeds. This
              is the only place that error is ever shown: a failed create has
              no optimistic row to visibly not-appear, and a failed
              update/delete rolls back silently otherwise. */}
          {error && (
            <div className="mb-6">
              <ErrorBanner message={error} />
            </div>
          )}
          {/* Notes have their own hook/error, surfaced the same way. */}
          {notesError && (
            <div className="mb-6">
              <ErrorBanner message={notesError} />
            </div>
          )}
          {/* Reached only via an explicit deep link (Sidebar/keyboard nav
              never select these, see chapterGroups.ts and CourseReader's
              goToOffset) — surfaced so it isn't a silent, unexplained
              dead end rather than blocked outright. */}
          {section.kind !== "content" && (
            <div
              role="note"
              aria-label="Reading flow notice"
              className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-divider bg-accent-soft px-4 py-3 text-sm"
            >
              <span>{NON_CONTENT_BANNER_TEXT[section.kind]}</span>
              {section.chapter_label !== null && (
                <Link
                  href={`/course/${courseId}/chapter/${encodeURIComponent(section.chapter_label)}/test`}
                  className="shrink-0 font-medium text-accent-700 underline"
                >
                  Go to chapter test
                </Link>
              )}
            </div>
          )}
          {pages ? <p className="mb-1.5 text-[13px] text-muted-foreground">{pages}</p> : null}
          {/* Explicit heading (not part of the markdown body) so chapter-change
              focus management has a stable, deterministic target regardless of
              what heading levels the section's own source text happens to use. */}
          <h2 ref={headingRef} tabIndex={-1} className="mb-5 text-[30px] outline-none">
            {section.title}
          </h2>
          {mode === "source" ? (
            body.kind === "loading" ? (
              <p role="status" className="text-sm text-muted-foreground">
                Loading chapter…
              </p>
            ) : body.kind === "error" ? (
              <ErrorBanner message={body.message} />
            ) : (
              // Keyed on section id (same convention as PagesView/LessonPane
              // below): forces a fresh DOM subtree per section rather than
              // React patching text into the SAME nodes in place. Without
              // this, a stale painter effect run (its highlights/enabled
              // deps unchanged across a section switch — see
              // useHighlightPainter's caller comment above) could resolve
              // old Range objects against nodes React mutated in place,
              // painting a highlight onto the wrong section's text instead
              // of harmlessly pointing at detached nodes.
              <div
                ref={articleBodyRef}
                key={section.id}
                onMouseUp={handleArticleMouseUp}
                onClick={handleArticleClick}
              >
                <Markdown>{body.body}</Markdown>
              </div>
            )
          ) : mode === "pages" ? (
            section.asset_id && section.page_start !== null && section.page_end !== null ? (
              // Keyed on section id (same convention as the source-mode
              // article wrapper above): switching chapters is a fresh
              // document view, not a state transition
              // (PdfPagesView/HtmlPagesView's own per-assetId caches mean
              // this remount is cheap when the new section shares the same
              // book) — and it gives pagesRef a fresh node per section, so
              // a leftover selection/popover from the previous chapter's
              // pages can't outlive it.
              <div key={section.id} ref={pagesRef} onMouseUp={handlePagesMouseUp} onClick={handlePagesClick}>
                <PagesView
                  courseId={courseId}
                  assetId={section.asset_id}
                  pageStart={section.page_start}
                  pageEnd={section.page_end}
                  highlights={pdfHighlights}
                  enabled={mode === "pages"}
                  notes={notes}
                  onNoteGutterClick={handleNoteGutterClick}
                  onNoteClick={handleNoteClick}
                />
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Original pages aren&apos;t available for this section.
              </p>
            )
          ) : (
            // Keyed on section id: switching chapters while in lesson view is
            // a fresh pane, not a state transition — remounting gives it
            // clean initial state for free instead of a reset-in-effect.
            <LessonPane
              key={section.id}
              sectionId={section.id}
              onStatusChange={(status) => onLessonStatusChange(section.id, status)}
            />
          )}
          <div className="mt-8">
            <CardsCTA key={`cta-${section.id}`} sectionId={section.id} />
            <SectionCards key={`cards-${section.id}`} sectionId={section.id} />
          </div>
          {(previousTitle !== null || nextTitle !== null) && (
            <nav
              aria-label="Chapter navigation"
              className="mt-7 flex items-center justify-between gap-3 border-t border-divider pt-4"
            >
              {previousTitle !== null && (
                <button
                  type="button"
                  onClick={onPrevious}
                  aria-label={`Previous chapter: ${previousTitle}`}
                  className={NAV_LINK_CLASSES}
                >
                  <span aria-hidden="true">← </span>
                  {previousTitle}
                </button>
              )}
              {nextTitle !== null && (
                <button
                  type="button"
                  onClick={onNext}
                  aria-label={`Next chapter: ${nextTitle}`}
                  className={`${NAV_LINK_CLASSES} ml-auto`}
                >
                  {nextTitle}
                  <span aria-hidden="true"> →</span>
                </button>
              )}
            </nav>
          )}
        </article>
      </div>
      {selectionPopover && (
        // Rendered outside the scrollable column deliberately: it's
        // `position: fixed` (viewport-relative, matching
        // `range.getBoundingClientRect()`), and no ancestor here sets a
        // transform/filter that would turn it into a new containing block,
        // so its DOM position doesn't matter beyond "somewhere in this
        // subtree" — kept as a plain sibling rather than nested inside the
        // scrolling column to avoid any future clipping/stacking surprises
        // from that container's own `overflow-y-auto`.
        <SelectionPopover
          anchorRect={selectionPopover.anchorRect}
          onColor={handleSelectionColor}
          onExplain={handleSelectionExplain}
          onClose={closeSelectionPopover}
        />
      )}
      {editPopover && (
        // Same "plain sibling, not nested in the scrolling column" placement
        // rationale as SelectionPopover above.
        <HighlightEditPopover
          highlight={editPopover.highlight}
          anchorRect={editPopover.anchorRect}
          onSave={handleEditSave}
          onDelete={handleEditDelete}
          onExplain={handleEditExplain}
          onClose={closeEditPopover}
        />
      )}
      {pagesPopover &&
        (pagesPopover.selector && pagesPopover.page !== null ? (
          // Full color-picker toolbar — same component the source view
          // uses — whenever this selection resolved to a paintable
          // `[data-pdf-page]` anchor (see handlePagesMouseUp's comment).
          // Same "plain sibling, not nested in the scrolling column"
          // placement rationale as SelectionPopover/HighlightEditPopover
          // above.
          <SelectionPopover
            anchorRect={pagesPopover.anchorRect}
            onColor={handlePagesColor}
            onExplain={handlePagesAdd}
            onClose={closePagesPopover}
          />
        ) : (
          // Fallback for an unsupported browser or a selection that
          // couldn't resolve to a page anchor: Add to chat only, since
          // there's nothing to paint against.
          <AddToChatPopover
            anchorRect={pagesPopover.anchorRect}
            onAdd={handlePagesAdd}
            onClose={closePagesPopover}
          />
        ))}
      {pagesEditPopover && (
        // Same "plain sibling, not nested in the scrolling column" placement
        // rationale as SelectionPopover/HighlightEditPopover/pagesPopover
        // above.
        <HighlightEditPopover
          highlight={pagesEditPopover.highlight}
          anchorRect={pagesEditPopover.anchorRect}
          onSave={handlePagesEditSave}
          onDelete={handlePagesEditDelete}
          onExplain={handlePagesEditExplain}
          onClose={closePagesEditPopover}
        />
      )}
      {noteComposer && (
        // Composer for a new margin note (no onDelete). Same "plain sibling,
        // not nested in the scrolling column" placement rationale as the
        // highlight popovers above.
        <NotePopover
          anchorRect={noteComposer.anchorRect}
          onSave={handleNoteComposerSave}
          onClose={closeNoteComposer}
        />
      )}
      {noteEditPopover && (
        <NotePopover
          initialNote={noteEditPopover.note.note_md}
          anchorRect={noteEditPopover.anchorRect}
          onSave={handleNoteEditSave}
          onDelete={handleNoteEditDelete}
          onClose={closeNoteEditPopover}
        />
      )}
    </div>
  );
}
