import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { getDocument } from "pdfjs-dist";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import PdfPagesView from "@/components/reader/PdfPagesView";
import type { NoteOut } from "@/lib/api/client";

import { FakeIntersectionObserver, makeFakeDocument, makeFakePage } from "../support/fake-pdfjs";

vi.mock("@/lib/api/client", () => ({
  buildAssetFileUrl: vi.fn((assetId: string) => `https://mock/api/assets/${assetId}/file`),
}));

// jsdom has neither DOMMatrix nor Worker — same guard as pdf-pages-view.test.tsx.
vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerPort: null },
  getDocument: vi.fn(),
  TextLayer: class {
    render = vi.fn(() => Promise.resolve());
    cancel = vi.fn();
  },
}));

const mockedGetDocument = vi.mocked(getDocument);

function resolvedTask(doc: ReturnType<typeof makeFakeDocument>) {
  return { promise: Promise.resolve(doc) } as unknown as ReturnType<typeof getDocument>;
}

function note(overrides: Partial<NoteOut>): NoteOut {
  return {
    id: "note-1",
    course_id: "course-1",
    section_id: "sec-1",
    surface: "pdf",
    page: 1,
    anchor_y: 0.5,
    note_md: "a note",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

/** Renders page 1, drives its lazy-load observer, and returns once the page's
 * note gutter is in the DOM (the gutter lives inside the position:relative
 * wrapper, which mounts as soon as the page is near-viewport). */
async function renderPageWithGutter(props: {
  notes?: NoteOut[];
  onNoteGutterClick?: (page: number, anchorY: number, x: number, y: number) => void;
  onNoteClick?: (note: NoteOut, x: number, y: number) => void;
}) {
  mockedGetDocument.mockReturnValue(resolvedTask(makeFakeDocument({ 1: makeFakePage() })));
  render(<PdfPagesView assetId="asset-1" pageStart={1} pageEnd={1} {...props} />);

  const container = await screen.findByTestId("pdf-page-1");
  // The page's observer registers in a mount effect, which can land a tick
  // after findByTestId resolves (raced as this file's first, cold-worker
  // test) — acquire it asynchronously, never with a synchronous grab.
  const observer = await waitFor(() => {
    const found = FakeIntersectionObserver.instances.find((o) =>
      o.observed.includes(container),
    );
    if (!found) throw new Error("page observer not registered yet");
    return found;
  });
  observer.triggerIntersect(container);
  await screen.findByTestId("note-gutter-1");
}

describe("PdfPage margin-note gutter and pins", () => {
  let originalIntersectionObserver: typeof IntersectionObserver | undefined;

  beforeEach(() => {
    originalIntersectionObserver = globalThis.IntersectionObserver;
    FakeIntersectionObserver.instances = [];
    globalThis.IntersectionObserver =
      FakeIntersectionObserver as unknown as typeof IntersectionObserver;
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    globalThis.IntersectionObserver = originalIntersectionObserver as typeof IntersectionObserver;
  });

  it("renders a note pin positioned at its anchor_y fraction of the page height", async () => {
    await renderPageWithGutter({ notes: [note({ id: "n-mid", anchor_y: 0.5 })] });

    const pin = screen.getByTestId("note-pin-n-mid");
    // The whole point of a normalized anchor: a plain CSS top:% that tracks
    // the page height at any width, no JS geometry.
    expect(pin.style.top).toBe("50%");
  });

  it("only paints pins whose page matches (parent slices by page)", async () => {
    await renderPageWithGutter({
      notes: [note({ id: "on-1", page: 1 }), note({ id: "on-2", page: 2 })],
    });
    expect(screen.getByTestId("note-pin-on-1")).toBeInTheDocument();
    expect(screen.queryByTestId("note-pin-on-2")).not.toBeInTheDocument();
  });

  it("clicking a pin fires onNoteClick with that note", async () => {
    const onNoteClick = vi.fn();
    const n = note({ id: "n-click" });
    await renderPageWithGutter({ notes: [n], onNoteClick });

    fireEvent.click(screen.getByTestId("note-pin-n-click"));
    expect(onNoteClick).toHaveBeenCalledTimes(1);
    expect(onNoteClick.mock.calls[0][0]).toMatchObject({ id: "n-click" });
  });

  it("clicking the gutter fires onNoteGutterClick with the clamped anchor_y for the click point", async () => {
    const onNoteGutterClick = vi.fn();
    await renderPageWithGutter({ onNoteGutterClick });

    const gutter = screen.getByTestId("note-gutter-1");
    // jsdom doesn't lay out, so the rect is all-zero by default — pin the
    // gutter's geometry so anchor_y = (clientY - top) / height is meaningful.
    vi.spyOn(gutter, "getBoundingClientRect").mockReturnValue({
      top: 0,
      left: 900,
      right: 924,
      bottom: 800,
      width: 24,
      height: 800,
      x: 900,
      y: 0,
      toJSON: () => ({}),
    } as DOMRect);

    fireEvent.click(gutter, { clientX: 910, clientY: 400 });

    expect(onNoteGutterClick).toHaveBeenCalledTimes(1);
    const [page, anchorY] = onNoteGutterClick.mock.calls[0];
    expect(page).toBe(1);
    expect(anchorY).toBeCloseTo(0.5); // 400 / 800
  });
});
