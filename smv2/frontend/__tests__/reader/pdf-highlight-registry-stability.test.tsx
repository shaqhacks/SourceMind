import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { getDocument } from "pdfjs-dist";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReadingColumn from "@/components/reader/ReadingColumn";
import { highlightAtPoint } from "@/lib/annotations/hitTest";
import {
  findActiveCardsJob,
  listAssets,
  listCards,
  listHighlights,
  updateHighlight,
  type HighlightOut,
} from "@/lib/api/client";
import type { ReaderSection, SectionBodyState } from "@/lib/reader/types";

import { ok } from "../support/api-result";
import { FakeIntersectionObserver, makeFakeDocument, makeFakePage } from "../support/fake-pdfjs";

// ReadingColumn unconditionally mounts useHighlights (listHighlights/
// createHighlight/updateHighlight/deleteHighlight) and CardsCTA/SectionCards
// (listCards/findActiveCardsJob) below the article body regardless of view
// mode — same minimal-mock convention as pdf-highlight-edit.test.tsx. This
// file additionally needs listAssets/buildAssetFileUrl/buildAssetHtmlPageUrl/
// getAssetHtmlManifest because, UNLIKE that file, PagesView is NOT mocked
// here: this test needs the REAL PdfPagesView descendant mounted so its
// usePdfHighlightPainter genuinely runs alongside ReadingColumn's own
// (disabled, in pages mode) useHighlightPainter — that two-painter seam is
// exactly where the bug lived.
vi.mock("@/lib/api/client", () => ({
  listHighlights: vi.fn(),
  createHighlight: vi.fn(),
  updateHighlight: vi.fn(),
  deleteHighlight: vi.fn(),
  listCards: vi.fn(),
  findActiveCardsJob: vi.fn(),
  listAssets: vi.fn(),
  buildAssetFileUrl: vi.fn((assetId: string) => `https://mock/api/assets/${assetId}/file`),
  buildAssetHtmlPageUrl: vi.fn(
    (assetId: string, page: number) => `https://mock/api/assets/${assetId}/html/${page}`,
  ),
  getAssetHtmlManifest: vi.fn(),
}));

// Click-to-edit geometry resolution is mocked, same convention as
// pdf-highlight-edit.test.tsx (the geometry-dependent half is covered
// exhaustively/deterministically in hit-test.test.ts). This has NO effect
// on either painter under test here — neither useHighlightPainter nor
// usePdfHighlightPainter imports hitTest.ts; it only gives this test a
// controlled way to open the edit popover so Save can fire a REAL
// `updateOne` -> `highlights` state mutation, the same kind of change a
// genuine create/recolor/delete would produce.
vi.mock("@/lib/annotations/hitTest", () => ({
  highlightAtPoint: vi.fn(),
}));

// Same FakeTextLayer convention as pdf-highlight-paint.test.tsx: renders the
// fake page's OWN textContent items as real DOM text (unlike the no-op
// stub most other reader tests use for pdfjs-dist), which is what lets
// usePdfHighlightPainter's rangeForSelector genuinely resolve a highlight
// against real committed DOM instead of an empty container.
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
const mockedListHighlights = vi.mocked(listHighlights);
const mockedListCards = vi.mocked(listCards);
const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);
const mockedListAssets = vi.mocked(listAssets);
const mockedUpdateHighlight = vi.mocked(updateHighlight);
const mockedHighlightAtPoint = vi.mocked(highlightAtPoint);

function resolvedTask(doc: ReturnType<typeof makeFakeDocument>) {
  return { promise: Promise.resolve(doc) } as unknown as ReturnType<typeof getDocument>;
}

const SECTION: ReaderSection = {
  id: "sec-pdf-stability",
  title: "Chapter One",
  order_index: 0,
  page_start: 1,
  page_end: 1,
  lesson_status: "none",
  has_content: true,
  word_count: 100,
  kind: "content",
  chapter_label: null,
  asset_id: "asset-stability",
};

const BODY: SectionBodyState = { kind: "ready", body: "# Chapter One\n\nSource body." };

function makeHighlight(overrides: Partial<HighlightOut> = {}): HighlightOut {
  return {
    id: "hl-stability",
    course_id: "course-stability",
    section_id: SECTION.id,
    exact: "powerhouse",
    prefix: "The ",
    suffix: " of the cell",
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

function renderColumn() {
  return render(
    <ReadingColumn
      courseId="course-stability"
      section={SECTION}
      mode="pages"
      typography={{ fontSize: 18, measure: 78, lineHeight: 1.6 }}
      headingRef={{ current: null }}
      columnRef={{ current: null }}
      body={BODY}
      onLessonStatusChange={vi.fn()}
      onNext={vi.fn()}
      onPrevious={vi.fn()}
      nextTitle={null}
      previousTitle={null}
      onExplainSelection={vi.fn()}
    />,
  );
}

function triggerAllIntersections(): void {
  for (const observer of FakeIntersectionObserver.instances) {
    for (const el of observer.observed) observer.triggerIntersect(el);
  }
}

/** jsdom doesn't implement `document.elementFromPoint` at all (not even as
 * a stub returning null) — same convention as pdf-highlight-edit.test.tsx:
 * assign directly, delete again in afterEach. */
function stubElementFromPoint(returnValue: Element | null): void {
  (document as unknown as { elementFromPoint: (x: number, y: number) => Element | null }).elementFromPoint =
    vi.fn().mockReturnValue(returnValue);
}

function restoreStubs(): void {
  delete (document as unknown as { elementFromPoint?: unknown }).elementFromPoint;
}

describe("ReadingColumn pages mode: source painter must not clear the pdf painter's registry", () => {
  let originalIntersectionObserver: typeof IntersectionObserver | undefined;

  beforeEach(() => {
    originalIntersectionObserver = globalThis.IntersectionObserver;
    FakeIntersectionObserver.instances = [];
    globalThis.IntersectionObserver = FakeIntersectionObserver as unknown as typeof IntersectionObserver;
    fakeTextLayerInstances.length = 0;
    CSS.highlights.clear();

    mockedListCards.mockResolvedValue(ok([]));
    mockedFindActiveCardsJob.mockResolvedValue(null);
    mockedListAssets.mockResolvedValue(ok([]));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    restoreStubs();
    globalThis.IntersectionObserver = originalIntersectionObserver as typeof IntersectionObserver;
    CSS.highlights.clear();
  });

  it("a pdf highlight mutation does not wipe CSS.highlights via the (disabled) source painter's re-run", async () => {
    const user = userEvent.setup();
    const page = makeFakePage({
      textContent: { items: [{ str: "The powerhouse of the cell" }], styles: {} },
    });
    mockedGetDocument.mockReturnValue(resolvedTask(makeFakeDocument({ 1: page })));

    const highlight = makeHighlight({});
    mockedListHighlights.mockResolvedValue(ok([highlight]));

    renderColumn();

    await waitFor(() => expect(FakeIntersectionObserver.instances).toHaveLength(1));
    triggerAllIntersections();
    await waitFor(() => expect(fakeTextLayerInstances).toHaveLength(1));

    // Sanity check: the pdf highlight paints correctly before any mutation
    // — both painters agree at mount time.
    await waitFor(() => expect(CSS.highlights.get("hl-yellow")?.size).toBe(1));

    // Trigger a real `highlights` state mutation the way a user would:
    // click the painted highlight to open its edit popover, then Save with
    // no edits — a real `updateOne` -> `cacheRef` mutation -> new
    // `highlights` array reference, the same shape of change a genuine
    // create/recolor/delete produces. Only the click's own geometry
    // resolution is mocked (see the hitTest mock above); everything
    // downstream of `highlightAtPoint` — updateOne, both painters — is real.
    mockedHighlightAtPoint.mockReturnValue(highlight);
    mockedUpdateHighlight.mockResolvedValue(ok(highlight));

    const container = fakeTextLayerInstances[0].container;
    stubElementFromPoint(container);
    window.getSelection()?.removeAllRanges();
    fireEvent.click(container, { clientX: 5, clientY: 5 });

    expect(await screen.findByRole("dialog", { name: "Highlight actions" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(mockedUpdateHighlight).toHaveBeenCalledWith(highlight.id, { note_md: null });
    });

    // The bug: ReadingColumn's own (disabled, mode !== "source") source
    // painter re-ran on this `highlights` change (its `paintable` dep was a
    // fresh array every time) and called clearHighlightRegistry() AFTER
    // usePdfHighlightPainter — a descendant, whose layout effect commits
    // first — had just repainted, wiping the pdf highlight's registry entry
    // even though it's unchanged and still displayed. It must still be
    // there.
    expect(CSS.highlights.get("hl-yellow")?.size).toBe(1);
  });
});
