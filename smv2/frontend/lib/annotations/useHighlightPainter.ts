"use client";

import { useLayoutEffect, type RefObject } from "react";

import { rangeForSelector } from "@/lib/annotations/anchors";
import type { HighlightOut } from "@/lib/api/client";
import type { HighlightColor } from "@/lib/hooks/useHighlights";

const COLORS: readonly HighlightColor[] = ["yellow", "green", "blue", "pink"];

function registryName(color: HighlightColor): string {
  return `hl-${color}`;
}

// Computed once at module load, not per effect run: browser support for the
// CSS Custom Highlight API doesn't change during a session. `typeof CSS`/
// `typeof Highlight` guard the SSR/build-time module graph (no `CSS`/
// `Highlight` global exists in Node) as well as real unsupported browsers.
const supported =
  typeof CSS !== "undefined" && !!CSS.highlights && typeof Highlight !== "undefined";

/**
 * Deletes all four color registry names. `CSS.highlights` is a single
 * document-global registry, not scoped to this component instance — an
 * entry left behind from a previous render (a different section's ranges,
 * or the disabled/unsupported state) would otherwise keep painting on
 * whatever text now occupies the same names. Called on every effect
 * re-run's cleanup, on unmount, and on the disabled/unsupported branch —
 * always safe to call even when the API is unsupported.
 */
function clearRegistry(): void {
  if (!supported) return;
  for (const color of COLORS) {
    CSS.highlights.delete(registryName(color));
  }
}

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
    if (!enabled || !supported || !container) {
      clearRegistry();
      return undefined;
    }

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

    for (const color of COLORS) {
      const ranges = rangesByColor.get(color);
      if (ranges && ranges.length > 0) {
        CSS.highlights.set(registryName(color), new Highlight(...ranges));
      } else {
        CSS.highlights.delete(registryName(color));
      }
    }

    return () => {
      clearRegistry();
    };
    // containerRef omitted deliberately: a useRef's object identity never
    // changes across renders, so including it would be inert.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlights, enabled]);
}
