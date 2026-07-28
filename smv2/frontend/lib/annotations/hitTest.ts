/**
 * Click-to-edit hit-testing for painted highlights.
 *
 * Deliberately PURE (container + highlights + a point in, a HighlightOut or
 * null out) so it can be unit tested despite jsdom not doing real layout —
 * see __tests__/annotations/hit-test.test.ts, which stubs
 * `Range.prototype.getClientRects` per resolved highlight rather than
 * relying on jsdom to compute real geometry (it can't: `getClientRects()`
 * always returns an empty list in jsdom). ReadingColumn wires this to a
 * real `click` event's `clientX`/`clientY` in the browser, where
 * `getClientRects()` is real.
 */

import { flatten, resolveAgainst, toQuoteSelector } from "@/lib/annotations/anchors";
import type { HighlightOut } from "@/lib/api/client";

/**
 * Returns the smallest (shortest `exact`) highlight among `highlights`
 * whose resolved range contains the point (`clientX`, `clientY`), or null
 * if none does.
 *
 * Resolves each highlight's selector the same way the painter does
 * (`rangeForSelector` — the same anchors.ts matcher useHighlightPainter
 * uses), so hit-testing and painting can never disagree about where a
 * highlight sits. A highlight whose selector doesn't resolve against the
 * current DOM is skipped, same convention as the painter. "Smallest" is
 * measured by `exact.length`, not rect area: when two highlights overlap
 * (e.g. a highlight nested inside a longer one), the shorter selector is
 * the more specific target for a click.
 */
export function highlightAtPoint(
  container: HTMLElement,
  highlights: HighlightOut[],
  clientX: number,
  clientY: number,
): HighlightOut | null {
  if (highlights.length === 0) return null;

  let best: HighlightOut | null = null;
  // Flattened once for this click, not once per candidate highlight — every
  // highlight below resolves against this same container's same text.
  const flat = flatten(container);

  for (const highlight of highlights) {
    const range = resolveAgainst(flat, toQuoteSelector(highlight));
    if (!range) continue;

    const rects = range.getClientRects();
    let contains = false;
    for (let i = 0; i < rects.length; i++) {
      const rect = rects[i];
      if (clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom) {
        contains = true;
        break;
      }
    }
    if (!contains) continue;

    if (!best || highlight.exact.length < best.exact.length) {
      best = highlight;
    }
  }

  return best;
}
