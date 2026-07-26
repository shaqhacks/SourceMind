import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { getDocument } from "pdfjs-dist";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PdfPagesView from "@/components/reader/PdfPagesView";

import { FakeIntersectionObserver, makeFakeDocument, makeFakePage } from "../support/fake-pdfjs";

vi.mock("@/lib/api/client", () => ({
  buildAssetFileUrl: vi.fn((assetId: string) => `https://mock/api/assets/${assetId}/file`),
}));

// A minimal double for pdf.js 6.1.200's `TextLayer` class (confirmed via
// node_modules/pdfjs-dist/types/src/display/text_layer.d.ts: constructor
// takes { textContentSource, container, viewport }, has async render()
// and cancel()). Declared through vi.hoisted so vi.mock's factory below
// (itself hoisted above this file's imports) can reference it without
// hitting a TDZ error. Mirrors the real class just enough to assert the
// wiring: records construction args, appends one span into `container`
// (standing in for the real class's actual textDivs) so the test can
// prove the effect's cleanup clears it back out.
const { FakeTextLayer, fakeTextLayerInstances } = vi.hoisted(() => {
  const fakeTextLayerInstances: Array<{
    args: { textContentSource: unknown; container: HTMLElement; viewport: unknown };
    cancel: ReturnType<typeof vi.fn>;
    render: ReturnType<typeof vi.fn>;
  }> = [];

  class FakeTextLayer {
    args: { textContentSource: unknown; container: HTMLElement; viewport: unknown };
    cancel = vi.fn();
    render = vi.fn(() => Promise.resolve());

    constructor(args: { textContentSource: unknown; container: HTMLElement; viewport: unknown }) {
      this.args = args;
      const span = document.createElement("span");
      span.textContent = "mock text";
      args.container.appendChild(span);
      fakeTextLayerInstances.push(this);
    }
  }

  return { FakeTextLayer, fakeTextLayerInstances };
});

// jsdom has neither DOMMatrix nor Worker — see PdfPagesView.tsx's own
// comment on why the real module can't be imported here.
vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerPort: null },
  getDocument: vi.fn(),
  TextLayer: FakeTextLayer,
}));

const mockedGetDocument = vi.mocked(getDocument);

function resolvedTask(doc: ReturnType<typeof makeFakeDocument>) {
  return { promise: Promise.resolve(doc) } as unknown as ReturnType<typeof getDocument>;
}

describe("PdfPage text layer overlay", () => {
  let originalIntersectionObserver: typeof IntersectionObserver | undefined;

  beforeEach(() => {
    originalIntersectionObserver = globalThis.IntersectionObserver;
    FakeIntersectionObserver.instances = [];
    globalThis.IntersectionObserver =
      FakeIntersectionObserver as unknown as typeof IntersectionObserver;
    fakeTextLayerInstances.length = 0;
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    globalThis.IntersectionObserver = originalIntersectionObserver as typeof IntersectionObserver;
  });

  it("overlays a selectable .textLayer sibling on the canvas, built from the CSS-px viewport", async () => {
    const page = makeFakePage({ textContent: { items: [{ str: "Hello" }], styles: {} } });
    const doc = makeFakeDocument({ 1: page });
    mockedGetDocument.mockReturnValue(resolvedTask(doc));

    render(<PdfPagesView assetId="asset-textlayer" pageStart={1} pageEnd={1} />);

    await waitFor(() => expect(FakeIntersectionObserver.instances).toHaveLength(1));
    const pageContainer = screen.getByTestId("pdf-page-1");
    FakeIntersectionObserver.instances[0].triggerIntersect(pageContainer);

    const canvas = await screen.findByLabelText("Page 1");
    await waitFor(() => expect(fakeTextLayerInstances).toHaveLength(1));

    // The canvas and the .textLayer live as siblings inside a
    // position:relative wrapper sized to the canvas's CSS box.
    const wrapper = canvas.parentElement;
    expect(wrapper).not.toBeNull();
    expect(wrapper!.style.position).toBe("relative");

    const textLayerEl = wrapper!.querySelector<HTMLElement>(".textLayer");
    expect(textLayerEl).not.toBeNull();
    expect(textLayerEl!.parentElement).toBe(wrapper);
    expect(canvas.parentElement).toBe(wrapper);
    // canvas + .textLayer + the note gutter (a third sibling added with margin
    // notes); no note pins here since this render passes no notes.
    expect(wrapper!.children).toHaveLength(3);

    // TextLayer was built from the CSS-px viewport (page.getViewport({
    // scale }) — jsdom reports clientWidth 0, so the component's own
    // fallback scale of 1 applies: 600x800 per fake-pdfjs's makeFakePage),
    // targeting the .textLayer div, not the canvas.
    const instance = fakeTextLayerInstances[0];
    expect(instance.args.container).toBe(textLayerEl);
    expect(instance.args.viewport).toEqual({ width: 600, height: 800, scale: 1 });
    expect(page.getTextContent).toHaveBeenCalledTimes(1);
    expect(instance.args.textContentSource).toEqual({
      items: [{ str: "Hello" }],
      styles: {},
    });
    expect(textLayerEl!.style.getPropertyValue("--total-scale-factor")).toBe("1");

    // The mock's constructor stands in for real pdf.js's textDivs by
    // appending one span — proves the .textLayer container actually
    // receives the rendered content, not just holds a viewport reference.
    expect(textLayerEl!.childElementCount).toBe(1);
  });

  it("cancels the text layer and clears its container on unmount", async () => {
    const page = makeFakePage();
    const doc = makeFakeDocument({ 1: page });
    mockedGetDocument.mockReturnValue(resolvedTask(doc));

    const { unmount } = render(
      <PdfPagesView assetId="asset-textlayer-cleanup" pageStart={1} pageEnd={1} />,
    );

    await waitFor(() => expect(FakeIntersectionObserver.instances).toHaveLength(1));
    const pageContainer = screen.getByTestId("pdf-page-1");
    FakeIntersectionObserver.instances[0].triggerIntersect(pageContainer);

    const canvas = await screen.findByLabelText("Page 1");
    await waitFor(() => expect(fakeTextLayerInstances).toHaveLength(1));
    const textLayerEl = canvas.parentElement!.querySelector<HTMLElement>(".textLayer")!;
    expect(textLayerEl.childElementCount).toBe(1);

    const instance = fakeTextLayerInstances[0];
    unmount();

    expect(instance.cancel).toHaveBeenCalledTimes(1);
    // Cleanup clears the container directly (not via the ref, which React
    // may already have nulled by the time this passive-effect cleanup
    // runs) — no stale spans left behind on the detached node.
    expect(textLayerEl.childElementCount).toBe(0);
  });
});
