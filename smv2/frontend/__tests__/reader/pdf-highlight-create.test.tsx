import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReadingColumn from "@/components/reader/ReadingColumn";
import { CONTEXT_LEN } from "@/lib/annotations/anchors";
import { createHighlight, findActiveCardsJob, listCards, listHighlights } from "@/lib/api/client";
import type { ReaderSection, SectionBodyState } from "@/lib/reader/types";

import { ok } from "../support/api-result";

// Same minimal-mock convention as pdf-selection.test.tsx: ReadingColumn
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
// scope, which jsdom can't evaluate — same guard as pdf-selection.test.tsx.
// Unlike that file's stub (plain text, no page container), this one wraps
// the selectable text in a `[data-pdf-page]` div — the real `.textLayer`
// shape PdfPagesView's PdfPage renders (Task 3) — so a selection inside it
// can resolve to a page anchor and open the full color popover.
vi.mock("@/components/reader/PagesView", () => ({
  default: () => (
    <div data-pdf-page="2" className="textLayer">
      <p data-testid="pdf-stub-text">Selectable original page text for add to chat.</p>
    </div>
  ),
}));

const mockedListHighlights = vi.mocked(listHighlights);
const mockedListCards = vi.mocked(listCards);
const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);
const mockedCreateHighlight = vi.mocked(createHighlight);

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

const FULL_TEXT = "Selectable original page text for add to chat.";
const PHRASE = "original page text";

function makeCreatedHighlight() {
  const start = FULL_TEXT.indexOf(PHRASE);
  return ok({
    id: "hl-pdf-1",
    course_id: "course-1",
    section_id: "sec-pdf",
    exact: PHRASE,
    prefix: FULL_TEXT.slice(Math.max(0, start - CONTEXT_LEN), start),
    suffix: FULL_TEXT.slice(start + PHRASE.length, start + PHRASE.length + CONTEXT_LEN),
    occurrence: 0,
    page: 2,
    color: "green" as const,
    surface: "pdf" as const,
    note_md: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  });
}

/** Selects `phrase` within `el`'s single text node and installs it as the
 * live window selection — same technique as
 * __tests__/annotations/selection-popover.test.tsx's selectPhrase. */
function selectPhraseIn(el: HTMLElement, phrase: string): void {
  const textNode = el.firstChild as Text;
  const index = textNode.data.indexOf(phrase);
  if (index === -1) throw new Error(`phrase not found: ${phrase}`);
  const range = document.createRange();
  range.setStart(textNode, index);
  range.setEnd(textNode, index + phrase.length);
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

describe("Pages-view selection -> color highlight popover", () => {
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

  it("shows the full color popover (not Add-to-chat-only) for a selection inside a [data-pdf-page] container", async () => {
    renderColumn();

    const stub = await screen.findByTestId("pdf-stub-text");
    selectPhraseIn(stub, PHRASE);
    fireEvent.mouseUp(stub);

    expect(await screen.findByRole("dialog", { name: "Selection actions" })).toBeInTheDocument();
    for (const color of ["yellow", "green", "blue", "pink"] as const) {
      expect(screen.getByRole("button", { name: `Highlight ${color}` })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Add to chat" })).toBeInTheDocument();
  });

  it("picking a color creates a surface:pdf highlight anchored to the resolved page, and clears the selection", async () => {
    mockedCreateHighlight.mockResolvedValue(makeCreatedHighlight());
    const user = userEvent.setup();
    renderColumn();

    const stub = await screen.findByTestId("pdf-stub-text");
    selectPhraseIn(stub, PHRASE);
    fireEvent.mouseUp(stub);
    await screen.findByRole("dialog", { name: "Selection actions" });

    await user.click(screen.getByRole("button", { name: "Highlight green" }));

    const start = FULL_TEXT.indexOf(PHRASE);
    await waitFor(() => {
      expect(mockedCreateHighlight).toHaveBeenCalledWith("course-1", {
        section_id: "sec-pdf",
        exact: PHRASE,
        prefix: FULL_TEXT.slice(Math.max(0, start - CONTEXT_LEN), start),
        suffix: FULL_TEXT.slice(start + PHRASE.length, start + PHRASE.length + CONTEXT_LEN),
        occurrence: 0,
        page: 2,
        color: "green",
        surface: "pdf",
      });
    });

    expect(screen.queryByRole("dialog", { name: "Selection actions" })).not.toBeInTheDocument();
    expect(window.getSelection()?.isCollapsed).toBe(true);
  });

  it("Add to chat still fires onExplainSelection from the color popover", async () => {
    const onExplainSelection = vi.fn();
    const user = userEvent.setup();
    renderColumn(onExplainSelection);

    const stub = await screen.findByTestId("pdf-stub-text");
    selectPhraseIn(stub, PHRASE);
    fireEvent.mouseUp(stub);
    await screen.findByRole("dialog", { name: "Selection actions" });

    await user.click(screen.getByRole("button", { name: "Add to chat" }));

    expect(onExplainSelection).toHaveBeenCalledWith({ sectionId: "sec-pdf", exact: PHRASE });
    expect(mockedCreateHighlight).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Selection actions" })).not.toBeInTheDocument();
  });

  it("falls back to the Add-to-chat-only popover when the CSS Custom Highlight API is unsupported", async () => {
    // Same guarded delete/restore pattern as
    // __tests__/annotations/selection-popover.test.tsx's own
    // unsupported-browser test: deleting the global Highlight constructor
    // fails isHighlightApiSupported()'s `typeof Highlight !== "undefined"`
    // check without touching CSS.highlights itself. Restored in `finally`
    // so no later test in the suite observes the unsupported state.
    const globalRecord = globalThis as Record<string, unknown>;
    const originalHighlightCtor = globalRecord.Highlight;
    delete globalRecord.Highlight;

    try {
      renderColumn();

      const stub = await screen.findByTestId("pdf-stub-text");
      selectPhraseIn(stub, PHRASE);
      fireEvent.mouseUp(stub);

      // Add to chat still renders (the fallback), but the color swatches
      // and the SelectionPopover dialog do not — even though this
      // selection sits inside a real [data-pdf-page] container.
      expect(await screen.findByRole("button", { name: "Add to chat" })).toBeInTheDocument();
      expect(screen.queryByRole("dialog", { name: "Selection actions" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Highlight green" })).not.toBeInTheDocument();
    } finally {
      globalRecord.Highlight = originalHighlightCtor;
    }
  });
});
