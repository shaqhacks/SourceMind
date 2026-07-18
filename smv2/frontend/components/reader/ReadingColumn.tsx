"use client";

import { useCallback, useMemo, useRef, useState, type MouseEvent, type RefObject } from "react";
import Link from "next/link";

import ErrorBanner from "@/components/ErrorBanner";
import Markdown from "@/components/Markdown";
import { rangeForSelector, selectorFromRange, type QuoteSelector } from "@/lib/annotations/anchors";
import { highlightAtPoint } from "@/lib/annotations/hitTest";
import { isHighlightApiSupported, useHighlightPainter } from "@/lib/annotations/useHighlightPainter";
import type { HighlightOut, HighlightUpdateIn } from "@/lib/api/client";
import { useHighlights, type HighlightColor } from "@/lib/hooks/useHighlights";
import { prefsToCssVars, type TypographyPrefs } from "@/lib/hooks/useTypographyPrefs";
import type { ReaderSection, SectionBodyState, ViewMode } from "@/lib/reader/types";

import CardsCTA from "./CardsCTA";
import HighlightEditPopover from "./HighlightEditPopover";
import LessonPane, { type LessonDisplayStatus } from "./LessonPane";
import PagesView from "./PagesView";
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

const CHEVRON_ZONE_CLASSES =
  "group absolute inset-y-0 z-10 flex w-12 items-center justify-center text-muted-foreground/40 transition-colors hover:bg-muted-foreground/5 hover:text-foreground focus-visible:bg-muted-foreground/5 focus-visible:text-foreground";

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
  const { highlights, createFromSelector, updateOne, deleteOne } = useHighlights(courseId, section.id);
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
  const paintable = useMemo(
    () => highlights.filter((highlight) => highlight.section_id === section.id),
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
      // Fire-and-forget: useHighlights.createFromSelector already surfaces
      // failures via its own `error` state and the painter repaints from
      // that hook's state automatically once the row lands — nothing here
      // needs to await the result.
      void createFromSelector(selectionPopover.selector, color, section.page_start ?? null);
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
        : ({
            top: event.clientY,
            bottom: event.clientY,
            left: event.clientX,
            right: event.clientX,
            width: 0,
            height: 0,
          } as DOMRect);
      setEditPopover({ highlight: hit, anchorRect });
    },
    [paintable],
  );

  const handleEditSave = useCallback(
    (patch: HighlightUpdateIn) => {
      if (!editPopover) return;
      // Fire-and-forget, same convention as handleSelectionColor above:
      // updateOne surfaces failures via useHighlights' own `error` state
      // and the painter repaints automatically once state settles.
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

  return (
    <div className="relative flex min-h-0 flex-1">
      {previousTitle !== null && (
        <button
          type="button"
          onClick={onPrevious}
          aria-label={`Previous chapter: ${previousTitle}`}
          className={`${CHEVRON_ZONE_CLASSES} left-0`}
        >
          <span aria-hidden="true" className="text-2xl">
            ‹
          </span>
        </button>
      )}
      <div
        ref={columnRef}
        data-testid="reading-column"
        className="reading-column min-h-0 flex-1 overflow-y-auto"
        style={prefsToCssVars(typography)}
      >
        <article className="reading-measure mx-auto px-6 py-10 font-serif">
          {/* Reached only via an explicit deep link (Sidebar/keyboard nav
              never select these, see chapterGroups.ts and CourseReader's
              goToOffset) — surfaced so it isn't a silent, unexplained
              dead end rather than blocked outright. */}
          {section.kind !== "content" && (
            <div
              role="note"
              aria-label="Reading flow notice"
              className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-accent/30 bg-accent/5 px-4 py-3 text-sm"
            >
              <span>{NON_CONTENT_BANNER_TEXT[section.kind]}</span>
              {section.chapter_label !== null && (
                <Link
                  href={`/course/${courseId}/chapter/${encodeURIComponent(section.chapter_label)}/test`}
                  className="shrink-0 font-medium text-accent underline"
                >
                  Go to chapter test
                </Link>
              )}
            </div>
          )}
          {pages ? <p className="mb-2 font-sans text-sm text-muted-foreground">{pages}</p> : null}
          {/* Explicit heading (not part of the markdown body) so chapter-change
              focus management has a stable, deterministic target regardless of
              what heading levels the section's own source text happens to use. */}
          <h2
            ref={headingRef}
            tabIndex={-1}
            className="mb-6 font-sans text-2xl font-semibold outline-none"
          >
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
              // Keyed on section id: switching chapters is a fresh document
              // view, not a state transition (PdfPagesView/HtmlPagesView's
              // own per-assetId caches mean this remount is cheap when the
              // new section shares the same book).
              <PagesView
                key={section.id}
                courseId={courseId}
                assetId={section.asset_id}
                pageStart={section.page_start}
                pageEnd={section.page_end}
              />
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
          <div className="mt-8 border-t border-border pt-4">
            <CardsCTA key={`cta-${section.id}`} sectionId={section.id} />
            <SectionCards key={`cards-${section.id}`} sectionId={section.id} />
          </div>
        </article>
      </div>
      {nextTitle !== null && (
        <button
          type="button"
          onClick={onNext}
          aria-label={`Next chapter: ${nextTitle}`}
          className={`${CHEVRON_ZONE_CLASSES} right-0`}
        >
          <span aria-hidden="true" className="text-2xl">
            ›
          </span>
        </button>
      )}
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
    </div>
  );
}
