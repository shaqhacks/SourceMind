import { cleanup, render } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { useHighlightPainter } from "@/lib/annotations/useHighlightPainter";
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
    page: 3,
    color: "yellow",
    note_md: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

// A known DOM the anchors matcher (Task 1) can resolve against — two
// sentences, each containing a distinct phrase the tests target.
function Harness({ highlights, enabled }: { highlights: HighlightOut[]; enabled: boolean }) {
  const containerRef = useRef<HTMLDivElement>(null);
  useHighlightPainter(containerRef, highlights, enabled);
  return (
    <div ref={containerRef}>
      <p>The mitochondria is the powerhouse of the cell.</p>
      <p>Ion channels regulate membrane potential across the cell.</p>
    </div>
  );
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

describe("useHighlightPainter", () => {
  beforeEach(() => {
    registry().clear();
  });

  afterEach(() => {
    cleanup();
    registry().clear();
  });

  it("paints two highlights of different colors under their own hl-<color> names", () => {
    const highlights = [
      makeHighlight({ id: "hl-1", exact: "powerhouse", color: "yellow" }),
      makeHighlight({ id: "hl-2", exact: "membrane potential", color: "green" }),
    ];

    render(<Harness highlights={highlights} enabled />);

    expect(registry().get("hl-yellow")?.size).toBe(1);
    expect(registry().get("hl-green")?.size).toBe(1);
    expect(registry().get("hl-blue")).toBeUndefined();
    expect(registry().get("hl-pink")).toBeUndefined();
  });

  it("toggling enabled to false clears all four registry names", () => {
    const highlights = [
      makeHighlight({ id: "hl-1", exact: "powerhouse", color: "yellow" }),
      makeHighlight({ id: "hl-2", exact: "membrane potential", color: "green" }),
    ];

    const { rerender } = render(<Harness highlights={highlights} enabled />);
    expect(registry().get("hl-yellow")).toBeDefined();
    expect(registry().get("hl-green")).toBeDefined();

    rerender(<Harness highlights={highlights} enabled={false} />);

    expectEmptyRegistry();
  });

  it("unmount clears all four registry names", () => {
    const highlights = [
      makeHighlight({ id: "hl-1", exact: "powerhouse", color: "yellow" }),
      makeHighlight({ id: "hl-2", exact: "membrane potential", color: "blue" }),
    ];

    const { unmount } = render(<Harness highlights={highlights} enabled />);
    expect(registry().get("hl-yellow")).toBeDefined();
    expect(registry().get("hl-blue")).toBeDefined();

    unmount();

    expectEmptyRegistry();
  });

  it("an unresolved selector neither throws nor adds a range", () => {
    const highlights = [
      makeHighlight({ id: "hl-1", exact: "text that is not anywhere in the DOM", color: "yellow" }),
    ];

    expect(() => render(<Harness highlights={highlights} enabled />)).not.toThrow();

    expectEmptyRegistry();
  });

  it("a section with only one color leaves the other three names deleted", () => {
    const highlights = [makeHighlight({ id: "hl-1", exact: "powerhouse", color: "blue" })];

    render(<Harness highlights={highlights} enabled />);

    expect(registry().get("hl-blue")?.size).toBe(1);
    expect(registry().get("hl-yellow")).toBeUndefined();
    expect(registry().get("hl-green")).toBeUndefined();
    expect(registry().get("hl-pink")).toBeUndefined();
  });

  it("a resolved plus an unresolved highlight of the same color paints only the resolved one", () => {
    const highlights = [
      makeHighlight({ id: "hl-1", exact: "powerhouse", color: "pink" }),
      makeHighlight({ id: "hl-2", exact: "nonexistent phrase", color: "pink" }),
    ];

    render(<Harness highlights={highlights} enabled />);

    expect(registry().get("hl-pink")?.size).toBe(1);
  });
});
