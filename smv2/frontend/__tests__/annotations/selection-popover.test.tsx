import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CourseReader from "@/components/reader/CourseReader";
import SelectionPopover from "@/components/reader/SelectionPopover";
import {
  createHighlight,
  getChatHistory,
  getLlmUsage,
  getSection,
  listAssets,
  listCards,
  findActiveCardsJob,
  listChapters,
  listHighlights,
  listSections,
  type HighlightOut,
} from "@/lib/api/client";
import type { ReaderCourse, ReaderProgress } from "@/lib/reader/types";

import { err, ok } from "../support/api-result";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
  getSection: vi.fn(),
  saveProgress: vi.fn(),
  getLessonEstimate: vi.fn(),
  findActiveLessonJob: vi.fn(),
  generateLesson: vi.fn(),
  getLlmUsage: vi.fn(),
  getChatHistory: vi.fn(),
  sendChat: vi.fn(),
  listCards: vi.fn(),
  findActiveCardsJob: vi.fn(),
  generateCards: vi.fn(),
  listSections: vi.fn(),
  editOutline: vi.fn(),
  listChapters: vi.fn(),
  listAssets: vi.fn(),
  listHighlights: vi.fn(),
  createHighlight: vi.fn(),
  updateHighlight: vi.fn(),
  deleteHighlight: vi.fn(),
  buildAssetFileUrl: vi.fn((assetId: string) => `https://mock/api/assets/${assetId}/file`),
  buildAssetHtmlPageUrl: vi.fn(
    (assetId: string, page: number) => `https://mock/api/assets/${assetId}/html/${page}`,
  ),
  getAssetHtmlManifest: vi.fn(),
}));

// Same guard as course-reader.test.tsx/reading-column-highlights.test.tsx:
// the reader tree imports PagesView -> PdfPagesView -> pdfjs-dist at module
// scope, which jsdom can't evaluate.
vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerPort: null },
  getDocument: vi.fn(),
  TextLayer: class {
    render = vi.fn(() => Promise.resolve());
    cancel = vi.fn();
  },
}));

const mockedGetSection = vi.mocked(getSection);
const mockedGetLlmUsage = vi.mocked(getLlmUsage);
const mockedListCards = vi.mocked(listCards);
const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);
const mockedListSections = vi.mocked(listSections);
const mockedListChapters = vi.mocked(listChapters);
const mockedListAssets = vi.mocked(listAssets);
const mockedListHighlights = vi.mocked(listHighlights);
const mockedCreateHighlight = vi.mocked(createHighlight);
const mockedGetChatHistory = vi.mocked(getChatHistory);

const COURSE: ReaderCourse = {
  id: "course-sel",
  title: "Selection Course",
  sections: [
    {
      id: "sec-1",
      title: "Chapter One",
      order_index: 0,
      page_start: 1,
      page_end: 5,
      lesson_status: "none",
      has_content: true,
      word_count: 100,
      kind: "content",
      chapter_label: null,
      asset_id: null,
    },
  ],
};

const BODY = "Read the example passage below for context.";
const NO_PROGRESS: ReaderProgress = { section_id: null, scroll_pos: 0 };

function makeHighlight(overrides: Partial<HighlightOut>): HighlightOut {
  return {
    id: "hl-new",
    course_id: "course-sel",
    section_id: "sec-1",
    exact: "example passage",
    prefix: "Read the ",
    suffix: " below",
    occurrence: 0,
    page: 1,
    color: "green",
    note_md: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

/** Builds a Range over the first occurrence of `phrase` within `root`'s
 * text and installs it as the live window selection — mirrors
 * __tests__/annotations/anchors.test.ts's own Range-building helper, plus
 * actually pushing it through `window.getSelection()` the way a real
 * mouse-drag selection would. */
function selectPhrase(root: HTMLElement, phrase: string): void {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node: Text | null;
  while ((node = walker.nextNode() as Text | null)) {
    const index = node.data.indexOf(phrase);
    if (index !== -1) {
      const range = document.createRange();
      range.setStart(node, index);
      range.setEnd(node, index + phrase.length);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      return;
    }
  }
  throw new Error(`phrase not found: ${phrase}`);
}

describe("SelectionPopover", () => {
  const anchorRect = { top: 200, bottom: 220, left: 100, right: 200, width: 100 } as DOMRect;

  afterEach(() => {
    cleanup();
  });

  it("renders four color swatches and an Explain button, wired to their callbacks", async () => {
    const user = userEvent.setup();
    const onColor = vi.fn();
    const onExplain = vi.fn();
    const onClose = vi.fn();
    render(
      <SelectionPopover
        anchorRect={anchorRect}
        onColor={onColor}
        onExplain={onExplain}
        onClose={onClose}
      />,
    );

    expect(screen.getByRole("dialog", { name: "Selection actions" })).toBeInTheDocument();
    for (const color of ["yellow", "green", "blue", "pink"] as const) {
      expect(screen.getByRole("button", { name: `Highlight ${color}` })).toBeInTheDocument();
    }

    await user.click(screen.getByRole("button", { name: "Highlight green" }));
    expect(onColor).toHaveBeenCalledWith("green");

    await user.click(screen.getByRole("button", { name: "Explain" }));
    expect(onExplain).toHaveBeenCalledTimes(1);

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("ReadingColumn selection popover integration", () => {
  beforeEach(() => {
    mockedGetSection.mockImplementation((id: string) => {
      const section = COURSE.sections.find((candidate) => candidate.id === id);
      if (!section) throw new Error(`unexpected section id ${id}`);
      return Promise.resolve(
        ok({
          id: section.id,
          course_id: COURSE.id,
          title: section.title,
          order_index: section.order_index,
          page_start: section.page_start,
          page_end: section.page_end,
          kind: section.kind,
          chapter_label: section.chapter_label,
          asset_id: section.asset_id,
          body_md: BODY,
          content_hash: "hash",
          lesson_md: null,
          lesson_status: section.lesson_status,
          lesson_stale: false,
          lesson_model: null,
          lesson_prompt_version: null,
          extractor_version: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });
    mockedGetLlmUsage.mockResolvedValue(
      ok({ calls: 0, input_tokens: 0, output_tokens: 0, est_cost_usd: 0 }),
    );
    mockedListCards.mockResolvedValue(ok([]));
    mockedFindActiveCardsJob.mockResolvedValue(null);
    mockedListAssets.mockResolvedValue(ok([]));
    mockedListSections.mockResolvedValue(ok(COURSE.sections));
    mockedListChapters.mockResolvedValue(ok([]));
    mockedListHighlights.mockResolvedValue(ok([]));
    mockedGetChatHistory.mockResolvedValue(ok([]));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    window.getSelection()?.removeAllRanges();
    for (const name of ["hl-yellow", "hl-green", "hl-blue", "hl-pink"]) {
      CSS.highlights.delete(name);
    }
  });

  it("opens on a live selection, creates a highlight from the color swatch, and clears the selection", async () => {
    const user = userEvent.setup();
    mockedCreateHighlight.mockResolvedValue(ok(makeHighlight({})));

    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    const paragraph = await screen.findByText(/read the example passage/i);

    expect(screen.queryByRole("dialog", { name: "Selection actions" })).not.toBeInTheDocument();

    selectPhrase(paragraph, "example passage");
    fireEvent.mouseUp(paragraph);

    expect(await screen.findByRole("dialog", { name: "Selection actions" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Highlight green" }));

    await waitFor(() => {
      expect(mockedCreateHighlight).toHaveBeenCalledWith("course-sel", {
        section_id: "sec-1",
        exact: "example passage",
        prefix: "Read the ",
        suffix: " below for context.",
        occurrence: 0,
        page: 1,
        color: "green",
      });
    });

    // Popover closes and the live selection is cleared once a color is chosen.
    expect(screen.queryByRole("dialog", { name: "Selection actions" })).not.toBeInTheDocument();
    expect(window.getSelection()?.isCollapsed ?? true).toBe(true);
  });

  it("surfaces a failed highlight creation via an error banner instead of failing silently", async () => {
    const user = userEvent.setup();
    mockedCreateHighlight.mockResolvedValue(err(500));

    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    const paragraph = await screen.findByText(/read the example passage/i);

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    selectPhrase(paragraph, "example passage");
    fireEvent.mouseUp(paragraph);
    expect(await screen.findByRole("dialog", { name: "Selection actions" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Highlight green" }));

    await waitFor(() => {
      expect(mockedCreateHighlight).toHaveBeenCalled();
    });

    // No optimistic row exists for a create (see useHighlights' own
    // comment), so without this banner a failed create is a pure no-op:
    // the popover closes, the selection clears, and nothing ever appears.
    expect(await screen.findByRole("alert")).toHaveTextContent(/creating highlight failed/i);
  });

  it("does not open a popover for a plain click (collapsed selection)", async () => {
    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    const paragraph = await screen.findByText(/read the example passage/i);

    window.getSelection()?.removeAllRanges();
    fireEvent.mouseUp(paragraph);

    expect(screen.queryByRole("dialog", { name: "Selection actions" })).not.toBeInTheDocument();
  });

  it("does not open a popover when the CSS Custom Highlight API is unsupported", async () => {
    // Simulate an older Safari/Firefox that lacks the CSS Custom Highlight
    // API. vitest.setup.ts installs the global `Highlight` constructor as a
    // plain configurable property (same pattern used there); deleting it
    // here is enough to fail `isHighlightApiSupported()`'s
    // `typeof Highlight !== "undefined"` check without touching
    // `CSS.highlights` itself — the Map stays in place so
    // useHighlightPainter's own module-level `supported` flag (cached at
    // first import, unaffected by this per-test toggle) keeps calling
    // `CSS.highlights.delete(...)` on a real Map instead of throwing.
    // Restored in `finally` so no later test in the suite observes the
    // unsupported state.
    const globalRecord = globalThis as Record<string, unknown>;
    const originalHighlightCtor = globalRecord.Highlight;
    delete globalRecord.Highlight;

    try {
      render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
      const paragraph = await screen.findByText(/read the example passage/i);

      // Same real selection + mouseup that opens the popover in the
      // supported-path test above.
      selectPhrase(paragraph, "example passage");
      fireEvent.mouseUp(paragraph);

      // handleArticleMouseUp must bail before opening anything and before
      // ever creating a highlight row that could never be painted.
      expect(screen.queryByRole("dialog", { name: "Selection actions" })).not.toBeInTheDocument();
      expect(mockedCreateHighlight).not.toHaveBeenCalled();
    } finally {
      globalRecord.Highlight = originalHighlightCtor;
    }
  });

  it("Explain opens the chat drawer and closes the popover", async () => {
    const user = userEvent.setup();
    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    const paragraph = await screen.findByText(/read the example passage/i);

    expect(screen.queryByRole("complementary", { name: "Course chat" })).not.toBeInTheDocument();

    selectPhrase(paragraph, "example passage");
    fireEvent.mouseUp(paragraph);
    expect(await screen.findByRole("dialog", { name: "Selection actions" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Explain" }));

    expect(await screen.findByRole("complementary", { name: "Course chat" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Selection actions" })).not.toBeInTheDocument();
    expect(mockedCreateHighlight).not.toHaveBeenCalled();
    // Task 9: the selection is carried through, mapped to snake_case, and
    // shown as a chip above the composer, not silently dropped.
    expect(screen.getByText(/asking about/i)).toHaveTextContent(/example passage/i);
  });

  it("Escape closes the popover without creating a highlight", async () => {
    const user = userEvent.setup();
    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    const paragraph = await screen.findByText(/read the example passage/i);

    selectPhrase(paragraph, "example passage");
    fireEvent.mouseUp(paragraph);
    expect(await screen.findByRole("dialog", { name: "Selection actions" })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "Selection actions" })).not.toBeInTheDocument();
    expect(mockedCreateHighlight).not.toHaveBeenCalled();
  });
});
