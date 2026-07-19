import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CourseReader from "@/components/reader/CourseReader";
import HighlightEditPopover from "@/components/reader/HighlightEditPopover";
import { highlightAtPoint } from "@/lib/annotations/hitTest";
import {
  deleteHighlight,
  getChatHistory,
  getLlmUsage,
  getSection,
  listAssets,
  listCards,
  findActiveCardsJob,
  listChapters,
  listHighlights,
  listSections,
  updateHighlight,
  type HighlightOut,
} from "@/lib/api/client";
import type { ReaderCourse, ReaderProgress } from "@/lib/reader/types";

import { ok } from "../support/api-result";

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

// Same guard as course-reader.test.tsx/selection-popover.test.tsx: the
// reader tree imports PagesView -> PdfPagesView -> pdfjs-dist at module
// scope, which jsdom can't evaluate.
vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerPort: null },
  getDocument: vi.fn(),
  TextLayer: class {
    render = vi.fn(() => Promise.resolve());
    cancel = vi.fn();
  },
}));

// The geometry-dependent half of click-to-edit (resolving a click point to
// the painted highlight underneath it) is covered exhaustively and
// deterministically in hit-test.test.ts, which stubs
// Range.prototype.getClientRects — jsdom never lays out text for real, so
// a genuine click here could never land on anything. Mocking the module
// lets the integration tests below exercise ReadingColumn's own wiring
// around highlightAtPoint (guard order, onSave/onDelete/onExplain ->
// updateOne/deleteOne/onExplainSelection) without needing real browser
// geometry.
vi.mock("@/lib/annotations/hitTest", () => ({
  highlightAtPoint: vi.fn(),
}));

const mockedGetSection = vi.mocked(getSection);
const mockedGetLlmUsage = vi.mocked(getLlmUsage);
const mockedListCards = vi.mocked(listCards);
const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);
const mockedListSections = vi.mocked(listSections);
const mockedListChapters = vi.mocked(listChapters);
const mockedListAssets = vi.mocked(listAssets);
const mockedListHighlights = vi.mocked(listHighlights);
const mockedUpdateHighlight = vi.mocked(updateHighlight);
const mockedDeleteHighlight = vi.mocked(deleteHighlight);
const mockedGetChatHistory = vi.mocked(getChatHistory);
const mockedHighlightAtPoint = vi.mocked(highlightAtPoint);

const COURSE: ReaderCourse = {
  id: "course-edit",
  title: "Edit Course",
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
    id: "hl-1",
    course_id: "course-edit",
    section_id: "sec-1",
    exact: "example passage",
    prefix: "Read the ",
    suffix: " below",
    occurrence: 0,
    page: 1,
    color: "green",
    surface: "source",
    note_md: "Existing note",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("HighlightEditPopover", () => {
  const anchorRect = { top: 200, bottom: 220, left: 100, right: 200, width: 100 } as DOMRect;

  afterEach(() => {
    cleanup();
  });

  it("prefills the note textarea from note_md and wires Save/swatch/Delete/Add to chat/Escape", async () => {
    const user = userEvent.setup();
    const highlight = makeHighlight({});
    const onSave = vi.fn();
    const onDelete = vi.fn();
    const onExplain = vi.fn();
    const onClose = vi.fn();

    render(
      <HighlightEditPopover
        highlight={highlight}
        anchorRect={anchorRect}
        onSave={onSave}
        onDelete={onDelete}
        onExplain={onExplain}
        onClose={onClose}
      />,
    );

    expect(screen.getByRole("dialog", { name: "Highlight actions" })).toBeInTheDocument();
    const textarea = screen.getByRole("textbox", { name: "Highlight note" }) as HTMLTextAreaElement;
    expect(textarea.value).toBe("Existing note");

    await user.clear(textarea);
    await user.type(textarea, "Updated note");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledWith({ note_md: "Updated note" });

    await user.click(screen.getByRole("button", { name: "Highlight blue" }));
    expect(onSave).toHaveBeenCalledWith({ color: "blue" });

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Add to chat" }));
    expect(onExplain).toHaveBeenCalledTimes(1);

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("prefills an empty textarea when note_md is null", () => {
    const highlight = makeHighlight({ note_md: null });
    render(
      <HighlightEditPopover
        highlight={highlight}
        anchorRect={anchorRect}
        onSave={vi.fn()}
        onDelete={vi.fn()}
        onExplain={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    const textarea = screen.getByRole("textbox", { name: "Highlight note" }) as HTMLTextAreaElement;
    expect(textarea.value).toBe("");
  });

  // The empty-note convention this component picked: Save sends `null`,
  // never `""`, when the textarea is empty/whitespace-only — matching
  // HighlightUpdateIn's own documented "explicit null clears the note"
  // semantics (see the docstring on schema.d.ts's HighlightUpdateIn),
  // rather than leaving a value that reads the same in the UI but isn't
  // the same "no note" state server-side.
  it("sends note_md: null (not an empty string) when Save is clicked with an emptied note", async () => {
    const user = userEvent.setup();
    const highlight = makeHighlight({ note_md: "Existing note" });
    const onSave = vi.fn();
    render(
      <HighlightEditPopover
        highlight={highlight}
        anchorRect={anchorRect}
        onSave={onSave}
        onDelete={vi.fn()}
        onExplain={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    const textarea = screen.getByRole("textbox", { name: "Highlight note" });
    await user.clear(textarea);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledWith({ note_md: null });
  });
});

describe("ReadingColumn click-to-edit integration", () => {
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

  it("opens the edit popover for the highlight highlightAtPoint resolves, Save calls updateOne and closes it", async () => {
    const user = userEvent.setup();
    const highlight = makeHighlight({});
    mockedListHighlights.mockResolvedValue(ok([highlight]));
    mockedHighlightAtPoint.mockReturnValue(highlight);
    mockedUpdateHighlight.mockResolvedValue(ok({ ...highlight, note_md: "Existing note" }));

    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    const paragraph = await screen.findByText(/read the example passage/i);

    window.getSelection()?.removeAllRanges();
    fireEvent.click(paragraph, { clientX: 10, clientY: 10 });

    expect(await screen.findByRole("dialog", { name: "Highlight actions" })).toBeInTheDocument();
    expect(mockedHighlightAtPoint).toHaveBeenCalledWith(
      expect.any(HTMLElement),
      expect.arrayContaining([highlight]),
      10,
      10,
    );

    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(mockedUpdateHighlight).toHaveBeenCalledWith(highlight.id, { note_md: "Existing note" });
    });
    expect(screen.queryByRole("dialog", { name: "Highlight actions" })).not.toBeInTheDocument();
  });

  it("does not open the edit popover when highlightAtPoint finds nothing under the click", async () => {
    mockedListHighlights.mockResolvedValue(ok([]));
    mockedHighlightAtPoint.mockReturnValue(null);

    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    const paragraph = await screen.findByText(/read the example passage/i);

    window.getSelection()?.removeAllRanges();
    fireEvent.click(paragraph, { clientX: 10, clientY: 10 });

    expect(screen.queryByRole("dialog", { name: "Highlight actions" })).not.toBeInTheDocument();
  });

  it("does not open the edit popover for a click that ends a live drag-selection", async () => {
    const highlight = makeHighlight({});
    mockedListHighlights.mockResolvedValue(ok([highlight]));
    mockedHighlightAtPoint.mockReturnValue(highlight);

    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    const paragraph = await screen.findByText(/read the example passage/i);

    // A real, non-collapsed selection — same shape a drag-select leaves
    // behind (mirrors selectPhrase() in selection-popover.test.tsx).
    const walker = document.createTreeWalker(paragraph, NodeFilter.SHOW_TEXT);
    const node = walker.nextNode() as Text;
    const range = document.createRange();
    range.setStart(node, 0);
    range.setEnd(node, 5);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);

    fireEvent.click(paragraph, { clientX: 10, clientY: 10 });

    // A click ending a drag-select must never even reach the hit-test —
    // that click belongs to SelectionPopover's create-highlight flow, not
    // this one's.
    expect(mockedHighlightAtPoint).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Highlight actions" })).not.toBeInTheDocument();
  });

  it("Delete calls deleteOne and closes the popover", async () => {
    const user = userEvent.setup();
    const highlight = makeHighlight({});
    mockedListHighlights.mockResolvedValue(ok([highlight]));
    mockedHighlightAtPoint.mockReturnValue(highlight);
    mockedDeleteHighlight.mockResolvedValue({ ok: true, status: 204 });

    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    const paragraph = await screen.findByText(/read the example passage/i);

    window.getSelection()?.removeAllRanges();
    fireEvent.click(paragraph, { clientX: 10, clientY: 10 });
    expect(await screen.findByRole("dialog", { name: "Highlight actions" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(mockedDeleteHighlight).toHaveBeenCalledWith(highlight.id);
    });
    expect(screen.queryByRole("dialog", { name: "Highlight actions" })).not.toBeInTheDocument();
  });

  it("Add to chat bubbles sectionId/exact up, opens the chat drawer, and closes the popover", async () => {
    const user = userEvent.setup();
    const highlight = makeHighlight({});
    mockedListHighlights.mockResolvedValue(ok([highlight]));
    mockedHighlightAtPoint.mockReturnValue(highlight);

    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    const paragraph = await screen.findByText(/read the example passage/i);

    expect(screen.queryByRole("complementary", { name: "Course chat" })).not.toBeInTheDocument();

    window.getSelection()?.removeAllRanges();
    fireEvent.click(paragraph, { clientX: 10, clientY: 10 });
    expect(await screen.findByRole("dialog", { name: "Highlight actions" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add to chat" }));

    expect(await screen.findByRole("complementary", { name: "Course chat" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Highlight actions" })).not.toBeInTheDocument();
    // Task 9: firing Add to chat from a painted (existing) highlight carries
    // its exact text through the same path as a fresh selection.
    expect(screen.getByTitle(/example passage/i)).toHaveTextContent(/example passage/i);
  });
});
