"use client";

import { useLayoutEffect, type RefObject } from "react";

import { rangeForSelector } from "@/lib/annotations/anchors";
import {
  clearHighlightRegistry,
  HIGHLIGHT_API_SUPPORTED,
  HIGHLIGHT_COLORS,
  highlightRegistryName,
  isHighlightApiSupported,
} from "@/lib/annotations/highlightRegistry";
import { ensureHighlightStyles } from "@/lib/annotations/highlightStyles";
import type { HighlightOut } from "@/lib/api/client";
import type { HighlightColor } from "@/lib/hooks/useHighlights";

// Re-exported for existing importers (CourseReader.tsx, ReadingColumn.tsx) —
// the live check itself now lives in highlightRegistry.ts alongside the
// rest of the shared registry plumbing usePdfHighlightPainter also uses.
export { isHighlightApiSupported };

/**
 * Paints `highlights` into the CSS Custom Highlight API registry
 * (https://developer.mozilla.org/docs/Web/API/CSS_Custom_Highlight_API) over
 * `containerRef`'s rendered DOM: one `Highlight` per color, registered under
 * `hl-<color>` — matching the `::highlight(hl-<color>)` rules already
 * defined for the four HighlightColor tokens.
 *
 * Runs in `useLayoutEffect`, not `useEffect`: `rangeForSelector` walks the
 * container's actual committed DOM text (a TreeWalker over Text nodes), so
 * it must run against the DOM React just painted, before the browser's next
 * paint — not after, which is what plain `useEffect` would allow.
 *
 * A highlight whose selector doesn't resolve against the current DOM
 * (`rangeForSelector` returns null — source text changed underneath it, or
 * this is a stale/mismatched section mid-transition) is silently skipped,
 * never thrown: it still exists and is still listed elsewhere (NotesPanel),
 * it just isn't painted.
 */
export function useHighlightPainter(
  containerRef: RefObject<HTMLElement | null>,
  highlights: HighlightOut[],
  enabled: boolean,
): void {
  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!enabled || !HIGHLIGHT_API_SUPPORTED || !container) {
      clearHighlightRegistry();
      return undefined;
    }

    // The ::highlight(hl-*) paint rules are injected at runtime, not via
    // globals.css (Turbopack/Lightning-CSS chokes on the pseudo-element at
    // build time — see highlightStyles.ts). Idempotent, so calling it on
    // every effect run is fine.
    ensureHighlightStyles();

    const rangesByColor = new Map<HighlightColor, Range[]>();
    for (const highlight of highlights) {
      const range = rangeForSelector(container, {
        exact: highlight.exact,
        prefix: highlight.prefix,
        suffix: highlight.suffix,
        occurrence: highlight.occurrence,
      });
      if (!range) continue;
      const existing = rangesByColor.get(highlight.color);
      if (existing) {
        existing.push(range);
      } else {
        rangesByColor.set(highlight.color, [range]);
      }
    }

    for (const color of HIGHLIGHT_COLORS) {
      const ranges = rangesByColor.get(color);
      if (ranges && ranges.length > 0) {
        CSS.highlights.set(highlightRegistryName(color), new Highlight(...ranges));
      } else {
        CSS.highlights.delete(highlightRegistryName(color));
      }
    }

    return () => {
      clearHighlightRegistry();
    };
    // containerRef omitted deliberately: a useRef's object identity never
    // changes across renders, so including it would be inert.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlights, enabled]);
}
