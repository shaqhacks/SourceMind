import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReadingColumn from "@/components/reader/ReadingColumn";
import { findActiveCardsJob, listCards, listHighlights } from "@/lib/api/client";
import type { ReaderSection, SectionBodyState } from "@/lib/reader/types";

import { ok } from "../support/api-result";

// ReadingColumn unconditionally mounts useHighlights (listHighlights) and,
// regardless of view mode, CardsCTA/SectionCards (listCards,
// findActiveCardsJob) below the article body — all three need a resolved
// mock or their mount-time fetches throw on an unmocked vi.fn(). Mirrors
// the minimal-mock convention in reading-column-highlights.test.tsx.
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
// scope, which jsdom can't evaluate (see other reader tests' identical
// guard). This task's own selection logic doesn't care what renders the
// pages — only that real, selectable text sits inside the pagesRef
// wrapper — so a plain stand-in with a real text node is enough, per the
// task brief's "OR render a stand-in that puts selectable text inside the
// pagesRef wrapper" fallback.
vi.mock("@/components/reader/PagesView", () => ({
  default: () => (
    <p data-testid="pdf-stub-text">Selectable original page text for add to chat.</p>
  ),
}));

const mockedListHighlights = vi.mocked(listHighlights);
const mockedListCards = vi.mocked(listCards);
const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);

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

/** Selects the full text content of `el` via document.createRange +
 * window.getSelection, the jsdom-supported subset of the Selection API
 * this component's handler reads from (rangeCount, isCollapsed,
 * anchorNode/focusNode, getRangeAt, toString). */
function selectAllTextIn(el: HTMLElement): void {
  const range = document.createRange();
  range.selectNodeContents(el);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}

function collapseSelectionIn(el: HTMLElement): void {
  const range = document.createRange();
  range.selectNodeContents(el);
  range.collapse(true);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
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

describe("Pages-view selection -> Add to chat popover", () => {
  beforeEach(() => {
    mockedListHighlights.mockResolvedValue(ok([]));
    mockedListCards.mockResolvedValue(ok([]));
    mockedFindActiveCardsJob.mockResolvedValue(null);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    window.getSelection()?.removeAllRanges();
  });

  it("shows Add to chat on a live pages-mode selection, wired to onExplainSelection with the section id", async () => {
    const onExplainSelection = vi.fn();
    renderColumn(onExplainSelection);

    const stub = await screen.findByTestId("pdf-stub-text");
    selectAllTextIn(stub);
    fireEvent.mouseUp(stub);

    const button = await screen.findByRole("button", { name: "Add to chat" });
    const user = userEvent.setup();
    await user.click(button);

    expect(onExplainSelection).toHaveBeenCalledWith({
      sectionId: "sec-pdf",
      exact: "Selectable original page text for add to chat.",
    });
    expect(screen.queryByRole("button", { name: "Add to chat" })).not.toBeInTheDocument();
    // The selection itself is cleared once added, same convention as the
    // source-view "Explain" flow (handleSelectionExplain).
    expect(window.getSelection()?.isCollapsed).toBe(true);
  });

  it("closes on Escape without firing onExplainSelection", async () => {
    const onExplainSelection = vi.fn();
    renderColumn(onExplainSelection);

    const stub = await screen.findByTestId("pdf-stub-text");
    selectAllTextIn(stub);
    fireEvent.mouseUp(stub);
    await screen.findByRole("button", { name: "Add to chat" });

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("button", { name: "Add to chat" })).not.toBeInTheDocument();
    expect(onExplainSelection).not.toHaveBeenCalled();
  });

  it("does not open a popover for a collapsed selection", async () => {
    renderColumn();

    const stub = await screen.findByTestId("pdf-stub-text");
    collapseSelectionIn(stub);
    fireEvent.mouseUp(stub);

    expect(screen.queryByRole("button", { name: "Add to chat" })).not.toBeInTheDocument();
  });

  it("does not render the source-view selection-color popover from a pages-mode selection", async () => {
    renderColumn();

    const stub = await screen.findByTestId("pdf-stub-text");
    selectAllTextIn(stub);
    fireEvent.mouseUp(stub);

    await screen.findByRole("button", { name: "Add to chat" });
    // SelectionPopover (source-mode create-highlight toolbar) uses this
    // aria-label; it must never mount from a pages-mode selection.
    expect(screen.queryByRole("dialog", { name: "Selection actions" })).not.toBeInTheDocument();
  });
});
