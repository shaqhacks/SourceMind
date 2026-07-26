import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CourseReader from "@/components/reader/CourseReader";
import {
  getChatHistory,
  getLlmUsage,
  getSection,
  listAssets,
  listCards,
  findActiveCardsJob,
  listChapters,
  listHighlights,
  listSections,
  sendChat,
} from "@/lib/api/client";
import type { ReaderCourse, ReaderProgress } from "@/lib/reader/types";

import { ok } from "../support/api-result";

// Task 9 end-to-end: a live text selection's "Add to chat" all the way
// through to sendChat receiving the mapped {section_id, exact} payload, and
// the pill clearing once that turn lands. The individual hops (SelectionPopover
// -> ReadingColumn -> CourseReader opens the drawer) are already covered in
// selection-popover.test.tsx/highlight-edit-popover.test.tsx; this file is
// the one that actually drives a message through to sendChat's arguments.

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
  listNotes: vi.fn(() => Promise.resolve({ data: [], ok: true, status: 200 })),
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

const mockedGetSection = vi.mocked(getSection);
const mockedGetLlmUsage = vi.mocked(getLlmUsage);
const mockedListCards = vi.mocked(listCards);
const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);
const mockedListSections = vi.mocked(listSections);
const mockedListChapters = vi.mocked(listChapters);
const mockedListAssets = vi.mocked(listAssets);
const mockedListHighlights = vi.mocked(listHighlights);
const mockedGetChatHistory = vi.mocked(getChatHistory);
const mockedSendChat = vi.mocked(sendChat);

const COURSE: ReaderCourse = {
  id: "course-explain",
  title: "Explain Course",
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

/** Same helper as selection-popover.test.tsx: builds a Range over the
 * first occurrence of `phrase` and installs it as the live selection. */
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

describe("Explain-in-chat wiring (CourseReader -> CourseChatDrawer -> sendChat)", () => {
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
  });

  it("Add to chat on a live selection maps camelCase -> snake_case and sendChat receives it on the next message; a follow-up send carries none", async () => {
    mockedSendChat.mockResolvedValue(ok({ reply_md: "It means...", citations: [] }));
    const user = userEvent.setup();

    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    const paragraph = await screen.findByText(/read the example passage/i);

    expect(screen.queryByRole("complementary", { name: "Course chat" })).not.toBeInTheDocument();

    selectPhrase(paragraph, "example passage");
    fireEvent.mouseUp(paragraph);
    expect(await screen.findByRole("dialog", { name: "Selection actions" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add to chat" }));

    const drawer = await screen.findByRole("complementary", { name: "Course chat" });
    expect(screen.getByTitle(/example passage/i)).toHaveTextContent(/example passage/i);

    await user.type(screen.getByLabelText(/message/i), "What does this mean?");
    await user.click(screen.getByRole("button", { name: /send/i }));

    // The bridge point: ReadingColumn's ExplainSelection ({sectionId,
    // exact}) has become ChatSelectionIn ({section_id, exact}) by the time
    // it reaches sendChat.
    await waitFor(() =>
      expect(mockedSendChat).toHaveBeenNthCalledWith(
        1,
        "course-explain",
        "What does this mean?",
        { section_id: "sec-1", exact: "example passage" },
      ),
    );

    // Attached to exactly one turn: the pill clears after the send lands.
    await waitFor(() => expect(screen.queryByRole("button", { name: "Remove context" })).not.toBeInTheDocument());

    await user.type(screen.getByLabelText(/message/i), "A follow-up, unrelated question");
    await user.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() =>
      expect(mockedSendChat).toHaveBeenNthCalledWith(
        2,
        "course-explain",
        "A follow-up, unrelated question",
      ),
    );

    // Still open and docked — Add to chat never closes the drawer mid-flow.
    expect(drawer).toBeInTheDocument();
  });
});
