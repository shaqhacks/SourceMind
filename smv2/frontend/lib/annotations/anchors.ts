/**
 * Text-quote anchoring over a rendered DOM subtree.
 *
 * Anchors live in the RENDERED text space (what the user selects), never in
 * body_md. selectorFromRange captures a selection as {exact, prefix, suffix,
 * occurrence}; rangeForSelector relocates it. occurrence disambiguates a
 * phrase that repeats. Matching is plain substring search over the container's
 * concatenated text nodes — both capture and resolve read the same DOM, so no
 * whitespace normalization is needed (and adding it would drift offsets).
 */

export type QuoteSelector = {
  exact: string;
  prefix: string;
  suffix: string;
  occurrence: number;
};

/** Narrows a persisted HighlightOut (or anything sharing its
 * exact/prefix/suffix/occurrence anchor fields) down to the plain
 * QuoteSelector `resolveAgainst` expects — shared by hitTest.ts,
 * useHighlightPainter, and usePdfHighlightPainter, which each used to
 * build this same object literal from a highlight themselves. */
export function toQuoteSelector(h: QuoteSelector): QuoteSelector {
  return { exact: h.exact, prefix: h.prefix, suffix: h.suffix, occurrence: h.occurrence };
}

export const CONTEXT_LEN = 32;

export type FlatText = {
  text: string;
  // For each character index i in `text`, nodeAt[i]/offsetAt[i] give the DOM
  // position of that character (its text node and offset within it).
  nodeAt: Text[];
  offsetAt: number[];
};

/**
 * Walks `container`'s Text nodes into one flat string plus a per-character
 * DOM back-reference. Exported (alongside `resolveAgainst` below) so a
 * caller resolving MANY selectors against the SAME container in one pass
 * (painting every highlight in a section, hit-testing a click against every
 * highlight on a page) can flatten once and reuse it, instead of
 * `rangeForSelector` silently re-walking the whole container's DOM per
 * selector — same text, same result, wasted work each time.
 */
export function flatten(container: HTMLElement): FlatText {
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let text = "";
  const nodeAt: Text[] = [];
  const offsetAt: number[] = [];
  let node: Node | null;
  while ((node = walker.nextNode())) {
    const t = node as Text;
    const s = t.data;
    for (let i = 0; i < s.length; i++) {
      nodeAt.push(t);
      offsetAt.push(i);
    }
    text += s;
  }
  return { text, nodeAt, offsetAt };
}

function rangeFromFlat(flat: FlatText, start: number, end: number): Range | null {
  if (start < 0 || end > flat.text.length || start >= end) return null;
  const range = document.createRange();
  range.setStart(flat.nodeAt[start], flat.offsetAt[start]);
  // end is exclusive; anchor to the last included char + 1.
  range.setEnd(flat.nodeAt[end - 1], flat.offsetAt[end - 1] + 1);
  return range;
}

// Character offset in `flat.text` for a Range/Selection boundary point
// (node, offset), or -1 if it can't be located within `container`'s text.
//
// Per the DOM spec, a boundary's `node` is NOT always a Text node: it can be
// an Element, in which case `offset` is a CHILD INDEX (the boundary sits
// between node.childNodes[offset - 1] and node.childNodes[offset]). Browsers
// produce Element-anchored boundaries routinely — double-click, triple-click,
// Ctrl/Cmd-A, selectNodeContents — so both shapes must resolve correctly.
//
// Rather than hand-rolling the subtree descent this implies (find the first
// Text node at/after a child index, skip children with no text, fall through
// to the next sibling, fall through to end-of-subtree, ...), this delegates
// to native Range.toString(): its DOM-spec algorithm concatenates the data
// of every Text node "contained" between (container, 0) and the boundary, in
// tree order — which is by definition exactly the flat-text length preceding
// that boundary, for both Text and Element boundaries. Re-deriving that walk
// by hand would just reimplement the same tree-walk with more room for bugs.
function flatIndexForBoundary(container: HTMLElement, node: Node, offset: number): number {
  if (!container.contains(node)) return -1;

  const limit = node.nodeType === Node.TEXT_NODE ? (node as Text).data.length : node.childNodes.length;
  const clamped = Math.max(0, Math.min(offset, limit));

  const marker = document.createRange();
  marker.setStart(container, 0);
  marker.setEnd(node, clamped);
  return marker.toString().length;
}

export function selectorFromRange(container: HTMLElement, range: Range): QuoteSelector | null {
  if (range.collapsed) return null;
  if (!container.contains(range.startContainer) || !container.contains(range.endContainer)) return null;

  const flat = flatten(container);
  const start = flatIndexForBoundary(container, range.startContainer, range.startOffset);
  const end = flatIndexForBoundary(container, range.endContainer, range.endOffset);
  if (start === -1 || end === -1 || start >= end) return null;

  const exact = flat.text.slice(start, end);
  if (exact.length === 0) return null;
  const prefix = flat.text.slice(Math.max(0, start - CONTEXT_LEN), start);
  const suffix = flat.text.slice(end, end + CONTEXT_LEN);

  // occurrence = number of matches of `exact` that start strictly before this one.
  let occurrence = 0;
  let from = flat.text.indexOf(exact);
  while (from !== -1 && from < start) {
    occurrence++;
    from = flat.text.indexOf(exact, from + 1);
  }
  return { exact, prefix, suffix, occurrence };
}

/**
 * Resolves a live pages-mode (PDF) selection to its page container: finds
 * the nearest `[data-pdf-page]` ancestor — pdf.js's `.textLayer` div,
 * tagged with `data-pdf-page={pageNumber}` by PdfPagesView's `PdfPage` —
 * and computes a selector scoped to THAT container (not the whole
 * multi-page wrapper), so `rangeForSelector` later resolves it back
 * against the same page's text only.
 *
 * Returns null for anything that can't become a `surface:"pdf"`
 * highlight: no `[data-pdf-page]` ancestor (e.g. HtmlPagesView's
 * pdf2htmlEX-enhanced view doesn't tag one), a selection whose focus node
 * falls outside that same container (a cross-page selection — MVP requires
 * both ends on one page, per the anchor's own page), a non-numeric
 * `data-pdf-page` value, or a selector `selectorFromRange` itself
 * couldn't capture (e.g. a collapsed range).
 *
 * Pure and DOM-only (no `window.getSelection()` call) so it's testable
 * without a live Selection — callers pass `selection.anchorNode`,
 * `selection.focusNode`, and `selection.getRangeAt(0)` directly.
 */
export function resolvePdfPageSelection(
  anchorNode: Node | null,
  focusNode: Node | null,
  range: Range,
): { selector: QuoteSelector; page: number } | null {
  const pageEl = anchorNode?.parentElement?.closest("[data-pdf-page]") as HTMLElement | null;
  if (!pageEl || !focusNode || !pageEl.contains(focusNode)) return null;

  const page = Number(pageEl.dataset.pdfPage);
  if (!Number.isFinite(page)) return null;

  const selector = selectorFromRange(pageEl, range);
  if (!selector) return null;

  return { selector, page };
}

/** Resolves a selector against an already-`flatten`ed container — the part
 * of `rangeForSelector` that doesn't need the container itself once its
 * text has been walked. Callers resolving multiple selectors against one
 * container in the same pass should flatten once and call this per
 * selector instead of calling `rangeForSelector` (which re-flattens every
 * time) in a loop. */
export function resolveAgainst(flat: FlatText, selector: QuoteSelector): Range | null {
  const { exact, occurrence } = selector;
  if (!exact) return null;

  let seen = 0;
  let from = flat.text.indexOf(exact);
  while (from !== -1) {
    if (seen === occurrence) return rangeFromFlat(flat, from, from + exact.length);
    seen++;
    from = flat.text.indexOf(exact, from + 1);
  }
  return null;
}

/** Thin wrapper — flattens `container` then resolves `selector` against it.
 * Kept for callers that only need to resolve ONE selector against a
 * container; a caller resolving many should call `flatten` once and
 * `resolveAgainst` per selector instead (see usePdfHighlightPainter,
 * useHighlightPainter, hitTest.ts). */
export function rangeForSelector(container: HTMLElement, selector: QuoteSelector): Range | null {
  return resolveAgainst(flatten(container), selector);
}
