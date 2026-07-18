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

export const CONTEXT_LEN = 32;

type FlatText = {
  text: string;
  // For each character index i in `text`, nodeAt[i]/offsetAt[i] give the DOM
  // position of that character (its text node and offset within it).
  nodeAt: Text[];
  offsetAt: number[];
};

function flatten(container: HTMLElement): FlatText {
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

export function rangeForSelector(container: HTMLElement, selector: QuoteSelector): Range | null {
  const { exact, occurrence } = selector;
  if (!exact) return null;
  const flat = flatten(container);

  let seen = 0;
  let from = flat.text.indexOf(exact);
  while (from !== -1) {
    if (seen === occurrence) return rangeFromFlat(flat, from, from + exact.length);
    seen++;
    from = flat.text.indexOf(exact, from + 1);
  }
  return null;
}
