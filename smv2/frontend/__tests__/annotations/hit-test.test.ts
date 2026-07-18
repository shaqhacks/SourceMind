import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { highlightAtPoint } from "@/lib/annotations/hitTest";
import type { HighlightOut } from "@/lib/api/client";

// Same container-building convention as anchors.test.ts.
function container(html: string): HTMLElement {
  const el = document.createElement("div");
  el.innerHTML = html;
  document.body.appendChild(el);
  return el;
}

function makeHighlight(overrides: Partial<HighlightOut>): HighlightOut {
  return {
    id: "hl-1",
    course_id: "course-1",
    section_id: "sec-1",
    exact: "brown",
    prefix: "",
    suffix: "",
    occurrence: 0,
    page: null,
    color: "yellow",
    note_md: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function rect(left: number, top: number, right: number, bottom: number): DOMRect {
  return {
    left,
    top,
    right,
    bottom,
    width: right - left,
    height: bottom - top,
    x: left,
    y: top,
    toJSON() {
      return this;
    },
  } as DOMRect;
}

/**
 * jsdom doesn't implement `Range.prototype.getClientRects` at all (there's
 * nothing there to lay out real geometry for, and no polyfill for it in
 * vitest.setup.ts) — the exact reason `highlightAtPoint` is factored as a
 * pure function taking a container/highlights/point rather than reading
 * geometry itself (see the module doc comment). Since the property doesn't
 * pre-exist, `vi.spyOn` has nothing to wrap; this assigns the method
 * directly instead, keyed by the resolved range's own text
 * (`range.toString()`), which is exactly the highlight's `exact` string for
 * a single-text-node match — giving each highlight whatever client rect(s)
 * the test wants it to have without needing jsdom to lay anything out for
 * real.
 */
function stubRectsByText(map: Record<string, DOMRect[]>): void {
  Range.prototype.getClientRects = vi.fn(function (this: Range) {
    return (map[this.toString()] ?? []) as unknown as DOMRectList;
  }) as unknown as () => DOMRectList;
}

describe("highlightAtPoint", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  afterEach(() => {
    vi.restoreAllMocks();
    // @ts-expect-error -- removing the per-test stub; jsdom has no real
    // implementation of this method to fall back to.
    delete Range.prototype.getClientRects;
  });

  it("returns the highlight whose rect contains the point", () => {
    const el = container("<p>The quick brown fox jumps over the lazy dog</p>");
    stubRectsByText({ brown: [rect(0, 0, 50, 20)] });

    const highlight = makeHighlight({ exact: "brown" });
    expect(highlightAtPoint(el, [highlight], 10, 10)).toBe(highlight);
  });

  it("returns null when the point falls outside every highlight's rects", () => {
    const el = container("<p>The quick brown fox jumps over the lazy dog</p>");
    stubRectsByText({ brown: [rect(0, 0, 50, 20)] });

    const highlight = makeHighlight({ exact: "brown" });
    expect(highlightAtPoint(el, [highlight], 500, 500)).toBeNull();
  });

  it("returns null for an empty highlight list", () => {
    const el = container("<p>The quick brown fox jumps over the lazy dog</p>");
    expect(highlightAtPoint(el, [], 10, 10)).toBeNull();
  });

  it("picks the shortest-exact highlight among overlapping matches", () => {
    const el = container("<p>The quick brown fox jumps over the lazy dog</p>");
    // "quick brown fox" wraps a wide rect; "brown" (nested inside it) has a
    // narrower rect that the outer one also covers — the point (60, 10)
    // falls inside both.
    stubRectsByText({
      "quick brown fox": [rect(0, 0, 200, 20)],
      brown: [rect(50, 0, 100, 20)],
    });

    const outer = makeHighlight({ id: "hl-outer", exact: "quick brown fox" });
    const inner = makeHighlight({ id: "hl-inner", exact: "brown" });

    expect(highlightAtPoint(el, [outer, inner], 60, 10)?.id).toBe("hl-inner");
    // Order-independent: the shortest match wins regardless of list order.
    expect(highlightAtPoint(el, [inner, outer], 60, 10)?.id).toBe("hl-inner");
  });

  it("skips a highlight whose selector doesn't resolve against the current DOM", () => {
    const el = container("<p>The quick brown fox jumps over the lazy dog</p>");
    stubRectsByText({ brown: [rect(0, 0, 50, 20)] });

    // "zebra" never appears in the container's text, so rangeForSelector
    // returns null for it — highlightAtPoint must skip it rather than throw
    // or treat it as a match, and still find the resolvable one.
    const unresolved = makeHighlight({ id: "hl-missing", exact: "zebra" });
    const resolvable = makeHighlight({ id: "hl-ok", exact: "brown" });

    expect(highlightAtPoint(el, [unresolved, resolvable], 10, 10)?.id).toBe("hl-ok");
  });

  it("matches a multi-rect (wrapped) range when the point is inside a later rect", () => {
    const el = container("<p>The quick brown fox jumps over the lazy dog</p>");
    // Simulates a highlight that wraps across a line break: two client
    // rects for one resolved range.
    stubRectsByText({
      brown: [rect(0, 0, 50, 20), rect(0, 20, 30, 40)],
    });

    const highlight = makeHighlight({ exact: "brown" });
    expect(highlightAtPoint(el, [highlight], 15, 30)?.id).toBe(highlight.id);
  });
});
