"use client";

import { useLayoutEffect } from "react";

import { flatten, resolveAgainst, toQuoteSelector } from "@/lib/annotations/anchors";
import {
  clearHighlightRegistry,
  commitRangesByColor,
  HIGHLIGHT_API_SUPPORTED,
} from "@/lib/annotations/highlightRegistry";
import { ensureHighlightStyles } from "@/lib/annotations/highlightStyles";
import type { HighlightOut } from "@/lib/api/client";
import type { HighlightColor } from "@/lib/hooks/useHighlights";

export interface PdfHighlightPage {
  /** A ready `.textLayer` container for one PDF page — `rangeForSelector`
   * walks its committed DOM text nodes, so this must already be in the DOM
   * with pdf.js's `TextLayer.render()` resolved (see PdfPage's
   * `textLayerReady`/`onTextLayerReady`). */
  container: HTMLElement;
  /** This page's own highlights only — the caller (PdfPagesView) is
   * expected to have already filtered the section's full `surface:"pdf"`
   * list down to `h.page === <this page's number>`. */
  highlights: HighlightOut[];
}

/**
 * Paints PDF-surface highlights across EVERY ready page's text layer into
 * ONE shared CSS Custom Highlight API registry entry per color.
 *
 * This has to be a single aggregating painter over all pages, never one
 * `useHighlightPainter`-style instance per `PdfPage`: `CSS.highlights` is a
 * single document-global registry keyed by name (`hl-<color>`), not scoped
 * to any one container, and `.set()` REPLACES whatever ranges were
 * registered under that name — it doesn't merge. If each page painted
 * independently, the last page's effect to run would silently overwrite
 * every earlier page's same-color highlights instead of adding to them.
 * This hook resolves ranges from every page first, groups them by color,
 * and calls `.set()` exactly once per color — so a single `hl-yellow`
 * entry can legitimately span page 3 and page 7 at the same time.
 *
 * Effect identity / churn: this runs in a `useLayoutEffect` keyed on the
 * `pages` array's reference and `enabled` — the same shape as
 * `useHighlightPainter`. That means the CALLER controls when a repaint
 * happens: `PdfPagesView` is expected to memoize `pages` (e.g. via
 * `useMemo` over its ready-container map + the highlight list) so an
 * unrelated re-render doesn't rebuild the same four registry names for no
 * reason, while an actual change — a page's text layer becoming ready/gone,
 * or the highlight list itself changing — produces a new `pages` reference
 * and correctly re-triggers the paint. Accepting the array (rather than,
 * say, a derived string key computed internally) keeps this hook simple and
 * lets the caller decide what "changed" means for its own ready-tracking
 * structure.
 *
 * Runs in `useLayoutEffect`, not `useEffect`, for the same reason as
 * `useHighlightPainter`: `rangeForSelector` walks each page's already-
 * committed DOM, and must do so before the browser's next paint.
 *
 * A highlight whose selector doesn't resolve against its page's current DOM
 * is silently skipped, never thrown — same convention as
 * `useHighlightPainter`.
 */
export function usePdfHighlightPainter(pages: PdfHighlightPage[], enabled: boolean): void {
  useLayoutEffect(() => {
    if (!enabled || !HIGHLIGHT_API_SUPPORTED) {
      clearHighlightRegistry();
      return undefined;
    }

    // The ::highlight(hl-*) paint rules are injected at runtime — see
    // highlightStyles.ts. Idempotent, so calling it on every effect run is
    // fine, and it's needed here too (not just from useHighlightPainter):
    // pages mode can be the very first highlight-painting surface a reader
    // visits in a session.
    ensureHighlightStyles();

    const rangesByColor = new Map<HighlightColor, Range[]>();
    for (const page of pages) {
      // Flattened once per page, not once per highlight on that page — every
      // highlight in `page.highlights` resolves against this same container.
      if (page.highlights.length === 0) continue;
      const flat = flatten(page.container);
      for (const highlight of page.highlights) {
        const range = resolveAgainst(flat, toQuoteSelector(highlight));
        if (!range) continue;
        const existing = rangesByColor.get(highlight.color);
        if (existing) {
          existing.push(range);
        } else {
          rangesByColor.set(highlight.color, [range]);
        }
      }
    }

    commitRangesByColor(rangesByColor);

    return () => {
      clearHighlightRegistry();
    };
  }, [pages, enabled]);
}
