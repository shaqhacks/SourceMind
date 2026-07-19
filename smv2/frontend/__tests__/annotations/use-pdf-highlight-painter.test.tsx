import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { usePdfHighlightPainter, type PdfHighlightPage } from "@/lib/annotations/usePdfHighlightPainter";
import type { HighlightOut } from "@/lib/api/client";

function makeHighlight(overrides: Partial<HighlightOut> = {}): HighlightOut {
  return {
    id: "hl-1",
    course_id: "course-1",
    section_id: "sec-1",
    exact: "quoted text",
    prefix: "before ",
    suffix: " after",
    occurrence: 0,
    page: 1,
    color: "yellow",
    surface: "pdf",
    note_md: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

// Detached-but-in-document containers, same convention as anchors.test.ts —
// these stand in for two PdfPage `.textLayer` containers. Built as plain
// DOM nodes (not React refs) because usePdfHighlightPainter's contract only
// needs real HTMLElements with committed text; it doesn't care where they
// came from, and building them this way sidesteps the ref-not-populated-
// until-after-commit timing issue a React-rendered pair of containers would
// otherwise force into the harness.
function container(html: string): HTMLElement {
  const el = document.createElement("div");
  el.innerHTML = html;
  document.body.appendChild(el);
  return el;
}

function Harness({ pages, enabled }: { pages: PdfHighlightPage[]; enabled: boolean }) {
  usePdfHighlightPainter(pages, enabled);
  return null;
}

function registry(): Map<string, Highlight> {
  return CSS.highlights;
}

const COLOR_NAMES = ["hl-yellow", "hl-green", "hl-blue", "hl-pink"] as const;

function expectEmptyRegistry(): void {
  for (const name of COLOR_NAMES) {
    expect(registry().get(name)).toBeUndefined();
  }
}

describe("usePdfHighlightPainter", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    registry().clear();
  });

  afterEach(() => {
    cleanup();
    registry().clear();
  });

  it("aggregates same-color ranges from TWO different page containers into ONE registry entry", () => {
    const page1 = container("<p>The mitochondria is the powerhouse of the cell.</p>");
    const page2 = container("<p>Ion channels regulate membrane potential across the cell.</p>");
    const pages: PdfHighlightPage[] = [
      {
        container: page1,
        highlights: [makeHighlight({ id: "hl-1", exact: "powerhouse", color: "yellow", page: 1 })],
      },
      {
        container: page2,
        highlights: [
          makeHighlight({ id: "hl-2", exact: "membrane potential", color: "yellow", page: 2 }),
        ],
      },
    ];

    render(<Harness pages={pages} enabled />);

    // The key aggregation invariant: a single hl-yellow entry spans BOTH
    // pages' ranges — not two separate entries, and not just the last
    // page's range overwriting the first's (which is exactly what would
    // happen if each page painted independently via its own CSS.highlights
    // .set() call instead of one aggregating painter).
    expect(registry().get("hl-yellow")?.size).toBe(2);
  });

  it("paints highlights of different colors under their own hl-<color> names, across pages", () => {
    const page1 = container("<p>The mitochondria is the powerhouse of the cell.</p>");
    const page2 = container("<p>Ion channels regulate membrane potential across the cell.</p>");
    const pages: PdfHighlightPage[] = [
      { container: page1, highlights: [makeHighlight({ id: "hl-1", exact: "powerhouse", color: "yellow" })] },
      {
        container: page2,
        highlights: [makeHighlight({ id: "hl-2", exact: "membrane potential", color: "green" })],
      },
    ];

    render(<Harness pages={pages} enabled />);

    expect(registry().get("hl-yellow")?.size).toBe(1);
    expect(registry().get("hl-green")?.size).toBe(1);
    expect(registry().get("hl-blue")).toBeUndefined();
    expect(registry().get("hl-pink")).toBeUndefined();
  });

  it("a page's own highlights only paint against that page's container, not a different page's text", () => {
    const page1 = container("<p>The mitochondria is the powerhouse of the cell.</p>");
    const page2 = container("<p>Ion channels regulate membrane potential across the cell.</p>");
    // This highlight's `exact` only exists in page2's text — scoping it to
    // page1's container in `pages` means rangeForSelector can never resolve
    // it there, so it must not be painted at all (not against page1, and
    // not silently against page2 either — the painter never cross-checks).
    const pages: PdfHighlightPage[] = [
      {
        container: page1,
        highlights: [makeHighlight({ id: "hl-1", exact: "membrane potential", color: "blue" })],
      },
      { container: page2, highlights: [] },
    ];

    render(<Harness pages={pages} enabled />);

    expect(registry().get("hl-blue")).toBeUndefined();
  });

  it("toggling enabled to false clears all four registry names", () => {
    const page1 = container("<p>The mitochondria is the powerhouse of the cell.</p>");
    const pages: PdfHighlightPage[] = [
      { container: page1, highlights: [makeHighlight({ id: "hl-1", exact: "powerhouse", color: "yellow" })] },
    ];

    const { rerender } = render(<Harness pages={pages} enabled />);
    expect(registry().get("hl-yellow")).toBeDefined();

    rerender(<Harness pages={pages} enabled={false} />);

    expectEmptyRegistry();
  });

  it("unmount clears all four registry names", () => {
    const page1 = container("<p>The mitochondria is the powerhouse of the cell.</p>");
    const page2 = container("<p>Ion channels regulate membrane potential across the cell.</p>");
    const pages: PdfHighlightPage[] = [
      { container: page1, highlights: [makeHighlight({ id: "hl-1", exact: "powerhouse", color: "yellow" })] },
      {
        container: page2,
        highlights: [makeHighlight({ id: "hl-2", exact: "membrane potential", color: "blue" })],
      },
    ];

    const { unmount } = render(<Harness pages={pages} enabled />);
    expect(registry().get("hl-yellow")).toBeDefined();
    expect(registry().get("hl-blue")).toBeDefined();

    unmount();

    expectEmptyRegistry();
  });

  it("an unresolved selector on any page neither throws nor adds a range", () => {
    const page1 = container("<p>The mitochondria is the powerhouse of the cell.</p>");
    const page2 = container("<p>Ion channels regulate membrane potential across the cell.</p>");
    const pages: PdfHighlightPage[] = [
      {
        container: page1,
        highlights: [makeHighlight({ id: "hl-1", exact: "text nowhere in page 1", color: "yellow" })],
      },
      {
        container: page2,
        highlights: [makeHighlight({ id: "hl-2", exact: "text nowhere in page 2", color: "yellow" })],
      },
    ];

    expect(() => render(<Harness pages={pages} enabled />)).not.toThrow();

    expectEmptyRegistry();
  });

  it("a resolved plus an unresolved highlight of the same color, split across pages, paints only the resolved one", () => {
    const page1 = container("<p>The mitochondria is the powerhouse of the cell.</p>");
    const page2 = container("<p>Ion channels regulate membrane potential across the cell.</p>");
    const pages: PdfHighlightPage[] = [
      { container: page1, highlights: [makeHighlight({ id: "hl-1", exact: "powerhouse", color: "pink" })] },
      {
        container: page2,
        highlights: [makeHighlight({ id: "hl-2", exact: "nonexistent phrase", color: "pink" })],
      },
    ];

    render(<Harness pages={pages} enabled />);

    expect(registry().get("hl-pink")?.size).toBe(1);
  });
});
