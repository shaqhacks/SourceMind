import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReadingColumn from "@/components/reader/ReadingColumn";
import { highlightAtPoint } from "@/lib/annotations/hitTest";
import {
  deleteHighlight,
  findActiveCardsJob,
  listCards,
  listHighlights,
  updateHighlight,
  type HighlightOut,
} from "@/lib/api/client";
import type { ReaderSection, SectionBodyState } from "@/lib/reader/types";

import { ok } from "../support/api-result";

// Same minimal-mock convention as pdf-highlight-create.test.tsx: ReadingColumn
// unconditionally mounts useHighlights (listHighlights) and
// CardsCTA/SectionCards (listCards, findActiveCardsJob) below the article
// body regardless of view mode.
vi.mock("@/lib/api/client", () => ({
  listNotes: vi.fn(() => Promise.resolve({ data: [], ok: true, status: 200 })),
  listHighlights: vi.fn(),
  createHighlight: vi.fn(),
  updateHighlight: vi.fn(),
  deleteHighlight: vi.fn(),
  listCards: vi.fn(),
  findActiveCardsJob: vi.fn(),
}));

// PagesView -> HtmlPagesView/PdfPagesView imports pdfjs-dist at module
// scope, which jsdom can't evaluate — same guard as
// pdf-highlight-create.test.tsx. Stubbed with the real `.textLayer`
// `[data-pdf-page]` shape PdfPagesView's PdfPage renders (Task 3/4), so
// `handlePagesClick`'s `.closest("[data-pdf-page]")` resolution has
// something real to walk up to.
vi.mock("@/components/reader/PagesView", () => ({
  default: () => (
    <div data-pdf-page="2" className="textLayer">
      <p data-testid="pdf-stub-text">Selectable original page text for add to chat.</p>
    </div>
  ),
}));

// The geometry-dependent half of click-to-edit (resolving a click point to
// the painted highlight underneath it) is covered exhaustively and
// deterministically in hit-test.test.ts, which stubs
// Range.prototype.getClientRects — jsdom never lays out text for real, so a
// genuine click here could never land on anything. Mocking the module (same
// convention as highlight-edit-popover.test.tsx's ReadingColumn
// click-to-edit integration suite) lets these tests exercise
// ReadingColumn's OWN wiring around highlightAtPoint — page-container
// resolution, guard order, onSave/onDelete/onExplain ->
// updateOne/deleteOne/onExplainSelection — without needing real browser
// geometry.
vi.mock("@/lib/annotations/hitTest", () => ({
  highlightAtPoint: vi.fn(),
}));

const mockedListHighlights = vi.mocked(listHighlights);
const mockedUpdateHighlight = vi.mocked(updateHighlight);
const mockedDeleteHighlight = vi.mocked(deleteHighlight);
const mockedListCards = vi.mocked(listCards);
const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);
const mockedHighlightAtPoint = vi.mocked(highlightAtPoint);

const SECTION: ReaderSection = {
  id: "sec-pdf",
  title: "Chapter One",
  order_index: 0,
  page_start: 1,
  page_end: 3,
  lesson_status: "none",
  has_content: true,
  word_count: 100,
  kind: "content",
  chapter_label: null,
  asset_id: "asset-1",
};

const BODY: SectionBodyState = { kind: "ready", body: "# Chapter One\n\nSource body." };

function makeHighlight(overrides: Partial<HighlightOut> = {}): HighlightOut {
  return {
    id: "hl-pdf-1",
    course_id: "course-1",
    section_id: "sec-pdf",
    exact: "original page text",
    prefix: "Selectable ",
    suffix: " for add to chat.",
    occurrence: 0,
    page: 2,
    color: "green",
    surface: "pdf",
    note_md: "Existing pdf note",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderColumn(onExplainSelection: () => void = vi.fn()) {
  return render(
    <ReadingColumn
      courseId="course-1"
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
      onExplainSelection={onExplainSelection}
    />,
  );
}

/** jsdom doesn't implement `document.elementFromPoint` at all (not even as
 * a stub that returns null) — `vi.spyOn` requires the property to already
 * exist, so it can't be used here. Assigning directly installs it as an
 * own property on `document` for the duration of the test; `restoreStubs`
 * (called in `afterEach`) deletes it again so a later test file/suite that
 * assumes the real jsdom absence doesn't observe a leftover stub. */
function stubElementFromPoint(returnValue: Element | null): void {
  (document as unknown as { elementFromPoint: (x: number, y: number) => Element | null }).elementFromPoint =
    vi.fn().mockReturnValue(returnValue);
}

function restoreStubs(): void {
  delete (document as unknown as { elementFromPoint?: unknown }).elementFromPoint;
}

/** Renders, stubs `document.elementFromPoint` to land on the pdf stub's
 * text node (a descendant of the mocked `[data-pdf-page="2"]` container),
 * and clicks it — the click→hit resolution path the implementation
 * factored specifically so it's stubbable this way in jsdom (no real
 * layout, no real `elementFromPoint`). Returns the stub for further
 * interaction. */
async function openEditPopoverViaClick(highlight: HighlightOut) {
  mockedListHighlights.mockResolvedValue(ok([highlight]));
  mockedHighlightAtPoint.mockReturnValue(highlight);

  renderColumn();

  const stub = await screen.findByTestId("pdf-stub-text");
  stubElementFromPoint(stub);
  window.getSelection()?.removeAllRanges();

  fireEvent.click(stub, { clientX: 15, clientY: 25 });

  expect(await screen.findByRole("dialog", { name: "Highlight actions" })).toBeInTheDocument();
  return stub;
}

describe("PDF pages-view click-to-edit", () => {
  beforeEach(() => {
    mockedListHighlights.mockResolvedValue(ok([]));
    mockedListCards.mockResolvedValue(ok([]));
    mockedFindActiveCardsJob.mockResolvedValue(null);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    restoreStubs();
    window.getSelection()?.removeAllRanges();
  });

  it("opens the edit popover for a collapsed click resolving to a painted pdf highlight, prefilled with its note", async () => {
    const highlight = makeHighlight({ note_md: "Existing pdf note" });

    await openEditPopoverViaClick(highlight);

    const textarea = screen.getByRole("textbox", { name: "Highlight note" }) as HTMLTextAreaElement;
    expect(textarea.value).toBe("Existing pdf note");
    expect(mockedHighlightAtPoint).toHaveBeenCalledWith(
      expect.any(HTMLElement),
      expect.arrayContaining([highlight]),
      15,
      25,
    );
  });

  it("does not open the edit popover when the click's selection is non-collapsed (a drag-select end)", async () => {
    const highlight = makeHighlight({});
    mockedListHighlights.mockResolvedValue(ok([highlight]));
    mockedHighlightAtPoint.mockReturnValue(highlight);

    renderColumn();

    const stub = await screen.findByTestId("pdf-stub-text");
    stubElementFromPoint(stub);

    // Real non-collapsed selection, same shape a drag-select leaves behind
    // (mirrors highlight-edit-popover.test.tsx's identical guard test).
    const textNode = stub.firstChild as Text;
    const range = document.createRange();
    range.setStart(textNode, 0);
    range.setEnd(textNode, 5);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);

    fireEvent.click(stub, { clientX: 15, clientY: 25 });

    expect(mockedHighlightAtPoint).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Highlight actions" })).not.toBeInTheDocument();
  });

  it("does not open the edit popover when the click lands outside any [data-pdf-page] container", async () => {
    const highlight = makeHighlight({});
    mockedListHighlights.mockResolvedValue(ok([highlight]));
    mockedHighlightAtPoint.mockReturnValue(highlight);

    renderColumn();
    // Click an in-tree node (same stub the other tests in this file click
    // to open the edit popover) so `handlePagesClick`'s React `onClick`
    // actually fires — a click on `document.body` never reaches it, since
    // the handler is bound to a descendant wrapper div, not the body.
    // `document.elementFromPoint` is stubbed to `null` (standing in for a
    // click whose point resolves to nothing with a `[data-pdf-page]`
    // ancestor, e.g. the "Page N" placeholder) so it's the `if (!pageEl)
    // return;` bail — not a handler that never ran — preventing the popover.
    const stub = await screen.findByTestId("pdf-stub-text");
    stubElementFromPoint(null);
    window.getSelection()?.removeAllRanges();

    fireEvent.click(stub, { clientX: 999, clientY: 999 });

    expect(mockedHighlightAtPoint).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Highlight actions" })).not.toBeInTheDocument();
  });

  it("Save with an edited note calls updateHighlight(id, { note_md }) and closes the popover", async () => {
    const user = userEvent.setup();
    const highlight = makeHighlight({ note_md: "Existing pdf note" });
    mockedUpdateHighlight.mockResolvedValue(ok({ ...highlight, note_md: "Updated pdf note" }));

    await openEditPopoverViaClick(highlight);

    const textarea = screen.getByRole("textbox", { name: "Highlight note" });
    await user.clear(textarea);
    await user.type(textarea, "Updated pdf note");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(mockedUpdateHighlight).toHaveBeenCalledWith(highlight.id, { note_md: "Updated pdf note" });
    });
    expect(screen.queryByRole("dialog", { name: "Highlight actions" })).not.toBeInTheDocument();
  });

  it("picking a color swatch calls updateHighlight(id, { color }) and closes the popover", async () => {
    const user = userEvent.setup();
    const highlight = makeHighlight({ color: "green" });
    mockedUpdateHighlight.mockResolvedValue(ok({ ...highlight, color: "blue" }));

    await openEditPopoverViaClick(highlight);

    await user.click(screen.getByRole("button", { name: "Highlight blue" }));

    await waitFor(() => {
      expect(mockedUpdateHighlight).toHaveBeenCalledWith(highlight.id, { color: "blue" });
    });
    expect(screen.queryByRole("dialog", { name: "Highlight actions" })).not.toBeInTheDocument();
  });

  it("Delete calls deleteHighlight(id) and closes the popover", async () => {
    const user = userEvent.setup();
    const highlight = makeHighlight({});
    mockedDeleteHighlight.mockResolvedValue({ ok: true, status: 204 });

    await openEditPopoverViaClick(highlight);

    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(mockedDeleteHighlight).toHaveBeenCalledWith(highlight.id);
    });
    expect(screen.queryByRole("dialog", { name: "Highlight actions" })).not.toBeInTheDocument();
  });

  it("Add to chat fires onExplainSelection with the highlight's sectionId/exact and closes the popover", async () => {
    const user = userEvent.setup();
    const onExplainSelection = vi.fn();
    const highlight = makeHighlight({});
    mockedListHighlights.mockResolvedValue(ok([highlight]));
    mockedHighlightAtPoint.mockReturnValue(highlight);

    renderColumn(onExplainSelection);
    const stub = await screen.findByTestId("pdf-stub-text");
    stubElementFromPoint(stub);
    window.getSelection()?.removeAllRanges();
    fireEvent.click(stub, { clientX: 15, clientY: 25 });
    expect(await screen.findByRole("dialog", { name: "Highlight actions" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add to chat" }));

    expect(onExplainSelection).toHaveBeenCalledWith({ sectionId: "sec-pdf", exact: "original page text" });
    expect(screen.queryByRole("dialog", { name: "Highlight actions" })).not.toBeInTheDocument();
  });
});
