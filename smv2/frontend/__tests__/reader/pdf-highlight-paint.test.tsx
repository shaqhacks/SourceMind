import { cleanup, render, waitFor } from "@testing-library/react";
import { getDocument } from "pdfjs-dist";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PdfPagesView from "@/components/reader/PdfPagesView";
import type { HighlightOut } from "@/lib/api/client";

import { FakeIntersectionObserver, makeFakeDocument, makeFakePage } from "../support/fake-pdfjs";

vi.mock("@/lib/api/client", () => ({
  buildAssetFileUrl: vi.fn((assetId: string) => `https://mock/api/assets/${assetId}/file`),
}));

// Unlike the plain FakeTextLayer used by PdfPagesView's other tests (which
// always appends the same static "mock text" span regardless of what was
// requested), this variant renders the fake page's own textContent items —
// needed here so two different pages can carry two different bodies of
// text and a highlight can be proven to resolve against ITS OWN page only.
const { FakeTextLayer, fakeTextLayerInstances } = vi.hoisted(() => {
  const fakeTextLayerInstances: Array<{ container: HTMLElement }> = [];

  class FakeTextLayer {
    cancel = vi.fn();
    render = vi.fn(() => Promise.resolve());

    constructor(args: {
      textContentSource: { items: Array<{ str?: string }> };
      container: HTMLElement;
    }) {
      const span = document.createElement("span");
      span.textContent = args.textContentSource.items.map((item) => item.str ?? "").join(" ");
      args.container.appendChild(span);
      fakeTextLayerInstances.push({ container: args.container });
    }
  }

  return { FakeTextLayer, fakeTextLayerInstances };
});

vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerPort: null },
  getDocument: vi.fn(),
  TextLayer: FakeTextLayer,
}));

const mockedGetDocument = vi.mocked(getDocument);

function resolvedTask(doc: ReturnType<typeof makeFakeDocument>) {
  return { promise: Promise.resolve(doc) } as unknown as ReturnType<typeof getDocument>;
}

function makeHighlight(overrides: Partial<HighlightOut> = {}): HighlightOut {
  return {
    id: "hl-1",
    course_id: "course-1",
    section_id: "sec-1",
    exact: "quoted text",
    prefix: "",
    suffix: "",
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

function registry(): Map<string, Highlight> {
  return CSS.highlights;
}

function triggerAllIntersections(): void {
  for (const observer of FakeIntersectionObserver.instances) {
    for (const el of observer.observed) observer.triggerIntersect(el);
  }
}

describe("PdfPagesView highlight painting (aggregating painter wiring)", () => {
  let originalIntersectionObserver: typeof IntersectionObserver | undefined;

  beforeEach(() => {
    originalIntersectionObserver = globalThis.IntersectionObserver;
    FakeIntersectionObserver.instances = [];
    globalThis.IntersectionObserver =
      FakeIntersectionObserver as unknown as typeof IntersectionObserver;
    fakeTextLayerInstances.length = 0;
    registry().clear();
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    globalThis.IntersectionObserver = originalIntersectionObserver as typeof IntersectionObserver;
    registry().clear();
  });

  it("paints a highlight once its page's text layer becomes ready", async () => {
    const page = makeFakePage({
      textContent: { items: [{ str: "The powerhouse of the cell" }], styles: {} },
    });
    mockedGetDocument.mockReturnValue(resolvedTask(makeFakeDocument({ 1: page })));

    const highlights = [makeHighlight({ id: "hl-1", exact: "powerhouse", color: "yellow", page: 1 })];

    render(<PdfPagesView assetId="asset-hl" pageStart={1} pageEnd={1} highlights={highlights} enabled />);

    await waitFor(() => expect(FakeIntersectionObserver.instances).toHaveLength(1));
    triggerAllIntersections();

    await waitFor(() => expect(fakeTextLayerInstances).toHaveLength(1));
    await waitFor(() => expect(registry().get("hl-yellow")?.size).toBe(1));
  });

  it("aggregates highlights from two DIFFERENT pages into ONE hl-<color> registry entry", async () => {
    const page1 = makeFakePage({
      textContent: { items: [{ str: "The powerhouse of the cell" }], styles: {} },
    });
    const page2 = makeFakePage({
      textContent: { items: [{ str: "Membrane potential across cells" }], styles: {} },
    });
    mockedGetDocument.mockReturnValue(resolvedTask(makeFakeDocument({ 1: page1, 2: page2 })));

    const highlights = [
      makeHighlight({ id: "hl-1", exact: "powerhouse", color: "yellow", page: 1 }),
      makeHighlight({ id: "hl-2", exact: "Membrane potential", color: "yellow", page: 2 }),
    ];

    render(<PdfPagesView assetId="asset-hl-agg" pageStart={1} pageEnd={2} highlights={highlights} enabled />);

    await waitFor(() => expect(FakeIntersectionObserver.instances).toHaveLength(2));
    triggerAllIntersections();

    await waitFor(() => expect(fakeTextLayerInstances).toHaveLength(2));
    // Both pages' ranges live under the SAME hl-yellow entry — the
    // aggregation invariant this whole task exists to guarantee. A
    // per-page painter would leave this at 1 (whichever page's effect ran
    // last overwriting the other's).
    await waitFor(() => expect(registry().get("hl-yellow")?.size).toBe(2));
  });

  it("a highlight tagged for a page whose text doesn't contain it is never painted", async () => {
    const page1 = makeFakePage({
      textContent: { items: [{ str: "The powerhouse of the cell" }], styles: {} },
    });
    const page2 = makeFakePage({
      textContent: { items: [{ str: "Membrane potential across cells" }], styles: {} },
    });
    mockedGetDocument.mockReturnValue(resolvedTask(makeFakeDocument({ 1: page1, 2: page2 })));

    // Tagged page: 1, but "Membrane potential" only exists on page 2's
    // text — PdfPagesView slices this into page 1's highlight list only
    // (h.page === pageNumber), so it can never resolve.
    const highlights = [
      makeHighlight({ id: "hl-3", exact: "Membrane potential", color: "green", page: 1 }),
    ];

    render(<PdfPagesView assetId="asset-hl-wrong-page" pageStart={1} pageEnd={2} highlights={highlights} enabled />);

    await waitFor(() => expect(FakeIntersectionObserver.instances).toHaveLength(2));
    triggerAllIntersections();

    await waitFor(() => expect(fakeTextLayerInstances).toHaveLength(2));
    expect(registry().get("hl-green")).toBeUndefined();
  });

  it("enabled=false never paints, even once the text layer is ready", async () => {
    const page = makeFakePage({
      textContent: { items: [{ str: "The powerhouse of the cell" }], styles: {} },
    });
    mockedGetDocument.mockReturnValue(resolvedTask(makeFakeDocument({ 1: page })));

    const highlights = [makeHighlight({ id: "hl-1", exact: "powerhouse", color: "yellow", page: 1 })];

    render(
      <PdfPagesView
        assetId="asset-hl-disabled"
        pageStart={1}
        pageEnd={1}
        highlights={highlights}
        enabled={false}
      />,
    );

    await waitFor(() => expect(FakeIntersectionObserver.instances).toHaveLength(1));
    triggerAllIntersections();

    await waitFor(() => expect(fakeTextLayerInstances).toHaveLength(1));
    expect(registry().get("hl-yellow")).toBeUndefined();
  });

  it("unmount clears the registry", async () => {
    const page = makeFakePage({
      textContent: { items: [{ str: "The powerhouse of the cell" }], styles: {} },
    });
    mockedGetDocument.mockReturnValue(resolvedTask(makeFakeDocument({ 1: page })));

    const highlights = [makeHighlight({ id: "hl-1", exact: "powerhouse", color: "yellow", page: 1 })];

    const { unmount } = render(
      <PdfPagesView assetId="asset-hl-unmount" pageStart={1} pageEnd={1} highlights={highlights} enabled />,
    );

    await waitFor(() => expect(FakeIntersectionObserver.instances).toHaveLength(1));
    triggerAllIntersections();
    await waitFor(() => expect(registry().get("hl-yellow")?.size).toBe(1));

    unmount();

    expect(registry().get("hl-yellow")).toBeUndefined();
  });
});
