import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CourseReaderClient from "@/components/reader/CourseReaderClient";
import {
  findActiveCardsJob,
  getCourse,
  getLlmUsage,
  getProgress,
  getSection,
  listCards,
  listChapters,
  listHighlights,
  listSections,
  saveProgress,
  type CourseOut,
  type ProgressOut,
  type SectionOut,
} from "@/lib/api/client";

import { err, ok } from "./support/api-result";

let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => mockSearchParams,
}));

vi.mock("@/lib/api/client", () => ({
  getCourse: vi.fn(),
  listSections: vi.fn(),
  getProgress: vi.fn(),
  getSection: vi.fn(),
  saveProgress: vi.fn(),
  getLlmUsage: vi.fn(),
  getChatHistory: vi.fn(),
  sendChat: vi.fn(),
  listCards: vi.fn(),
  findActiveCardsJob: vi.fn(),
  generateCards: vi.fn(),
  listChapters: vi.fn(),
  buildAssetFileUrl: vi.fn(),
  listHighlights: vi.fn(),
  createHighlight: vi.fn(),
  updateHighlight: vi.fn(),
  deleteHighlight: vi.fn(),
}));

// The reader tree imports PdfPagesView, which imports pdfjs-dist at
// module scope — jsdom has neither DOMMatrix nor Worker (see
// PdfPagesView.tsx's own guard for the latter), so the real module
// throws the moment it's evaluated. None of this file's tests exercise
// "pages" mode, so a minimal inert mock is enough.
vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerPort: null },
  getDocument: vi.fn(() => ({ promise: new Promise(() => {}) })),
}));

const mockedGetCourse = vi.mocked(getCourse);
const mockedListSections = vi.mocked(listSections);
const mockedGetProgress = vi.mocked(getProgress);
const mockedGetSection = vi.mocked(getSection);
const mockedSaveProgress = vi.mocked(saveProgress);
const mockedGetLlmUsage = vi.mocked(getLlmUsage);
const mockedListCards = vi.mocked(listCards);
const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);
const mockedListChapters = vi.mocked(listChapters);
const mockedListHighlights = vi.mocked(listHighlights);

function makeCourse(overrides: Partial<CourseOut> = {}): CourseOut {
  return {
    id: "course-1",
    title: "Distributed Systems",
    status: "ready",
    section_count: 1,
    failed_asset_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeSection(overrides: Partial<SectionOut> = {}): SectionOut {
  return {
    id: "sec-1",
    title: "Introduction",
    order_index: 0,
    page_start: 1,
    page_end: 5,
    lesson_status: "none",
    has_content: true,
    word_count: 100,
    kind: "content",
    chapter_label: null,
    asset_id: null,
    ...overrides,
  };
}

function makeProgress(overrides: Partial<ProgressOut> = {}): ProgressOut {
  return {
    course_id: "course-1",
    section_id: null,
    scroll_pos: 0,
    updated_at: null,
    ...overrides,
  };
}

function makeSectionDetail(id: string) {
  return {
    id,
    course_id: "course-1",
    title: id === "sec-2" ? "Deep Dive" : "Introduction",
    order_index: id === "sec-2" ? 1 : 0,
    page_start: 1,
    page_end: 5,
    kind: "content" as const,
    chapter_label: null,
    asset_id: null,
    body_md: `Body for ${id}`,
    content_hash: "hash",
    lesson_md: null,
    lesson_status: "none" as const,
    lesson_stale: false,
    lesson_model: null,
    lesson_prompt_version: null,
    extractor_version: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("CourseReaderClient", () => {
  beforeEach(() => {
    mockSearchParams = new URLSearchParams();
    mockedGetSection.mockResolvedValue(ok(makeSectionDetail("sec-1")));
    mockedSaveProgress.mockResolvedValue(ok(makeProgress()));
    mockedGetLlmUsage.mockResolvedValue(
      ok({ calls: 0, input_tokens: 0, output_tokens: 0, est_cost_usd: 0 }),
    );
    mockedListCards.mockResolvedValue(ok([]));
    mockedFindActiveCardsJob.mockResolvedValue(null);
    mockedListChapters.mockResolvedValue(ok([]));
    // useHighlights (mounted unconditionally by ReadingColumn, see Task 5)
    // fetches the course's highlights on mount/section change; no test in
    // this file exercises highlight content, so an empty list is enough to
    // keep it out of the way.
    mockedListHighlights.mockResolvedValue(ok([]));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    // useReaderView persists view mode to real localStorage (see
    // vitest.setup.ts's polyfill, not reset automatically) — course-1 is
    // reused across most tests here, so clear it defensively even though
    // none of this file's own tests currently change view mode.
    window.localStorage.clear();
  });

  it("shows a loading state before the fetches resolve", () => {
    mockedGetCourse.mockReturnValue(new Promise(() => {}));
    mockedListSections.mockReturnValue(new Promise(() => {}));
    mockedGetProgress.mockReturnValue(new Promise(() => {}));

    render(<CourseReaderClient courseId="course-1" />);

    expect(screen.getByText(/loading course/i)).toBeInTheDocument();
  });

  it("loads the course, its sections, and saved progress, then renders the reader", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedListSections.mockResolvedValue(ok([makeSection()]));
    mockedGetProgress.mockResolvedValue(ok(makeProgress()));

    render(<CourseReaderClient courseId="course-1" />);

    expect(await screen.findByRole("heading", { level: 2, name: /introduction/i })).toBeInTheDocument();
    expect(mockedGetCourse).toHaveBeenCalledWith("course-1");
    expect(mockedListSections).toHaveBeenCalledWith("course-1");
    expect(mockedGetProgress).toHaveBeenCalledWith("course-1");
  });

  it("shows a retryable error banner when a fetch fails, and recovers on retry", async () => {
    mockedGetCourse.mockResolvedValueOnce(err(500));
    mockedListSections.mockResolvedValue(ok([makeSection()]));
    mockedGetProgress.mockResolvedValue(ok(makeProgress()));

    const user = userEvent.setup();
    render(<CourseReaderClient courseId="course-1" />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/loading course failed/i);

    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    await user.click(screen.getByRole("button", { name: /retry/i }));

    expect(
      await screen.findByRole("heading", { level: 2, name: /introduction/i }),
    ).toBeInTheDocument();
  });

  it("treats a network failure (no status) as retryable", async () => {
    mockedGetCourse.mockResolvedValue(err());
    mockedListSections.mockResolvedValue(ok([]));
    mockedGetProgress.mockResolvedValue(ok(makeProgress()));

    render(<CourseReaderClient courseId="course-1" />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/could not reach the api/i);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("shows an empty-course message with a link back to the dashboard when there are no sections", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedListSections.mockResolvedValue(ok([]));
    mockedGetProgress.mockResolvedValue(ok(makeProgress()));

    render(<CourseReaderClient courseId="course-1" />);

    expect(await screen.findByText(/doesn.t have any chapters yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /dashboard/i })).toHaveAttribute("href", "/");
  });

  it("resumes at the saved section once loaded", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedListSections.mockResolvedValue(
      ok([
        makeSection({ id: "sec-1", title: "Introduction" }),
        makeSection({ id: "sec-2", title: "Deep Dive", order_index: 1 }),
      ]),
    );
    mockedGetProgress.mockResolvedValue(
      ok(makeProgress({ section_id: "sec-2", scroll_pos: 0.3 })),
    );
    mockedGetSection.mockImplementation((id: string) => Promise.resolve(ok(makeSectionDetail(id))));

    render(<CourseReaderClient courseId="course-1" />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /deep dive/i })).toHaveAttribute(
        "aria-current",
        "true",
      ),
    );
  });

  it("redirects a resumed practice/answers section to the nearest content section instead", async () => {
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedListSections.mockResolvedValue(
      ok([
        makeSection({ id: "sec-1", title: "Introduction", order_index: 0, kind: "content" }),
        makeSection({ id: "sec-practice", title: "Practice Set", order_index: 1, kind: "practice" }),
        makeSection({ id: "sec-2", title: "Deep Dive", order_index: 2, kind: "content" }),
      ]),
    );
    // Saved progress points at a section that's since become non-content
    // (e.g. an outline edit) — the reader must land on the nearest content
    // section (forward first: sec-2), never on sec-practice itself.
    mockedGetProgress.mockResolvedValue(
      ok(makeProgress({ section_id: "sec-practice", scroll_pos: 0.9 })),
    );
    mockedGetSection.mockImplementation((id: string) => Promise.resolve(ok(makeSectionDetail(id))));

    render(<CourseReaderClient courseId="course-1" />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /deep dive/i })).toHaveAttribute(
        "aria-current",
        "true",
      ),
    );
    expect(screen.queryByRole("button", { name: /practice set/i })).not.toBeInTheDocument();
  });

  it("a ?section= query param overrides saved progress (e.g. a chat citation click)", async () => {
    mockSearchParams = new URLSearchParams({ section: "sec-2" });
    mockedGetCourse.mockResolvedValue(ok(makeCourse()));
    mockedListSections.mockResolvedValue(
      ok([
        makeSection({ id: "sec-1", title: "Introduction" }),
        makeSection({ id: "sec-2", title: "Deep Dive", order_index: 1 }),
      ]),
    );
    // Saved progress points at sec-1 — the query param must win.
    mockedGetProgress.mockResolvedValue(
      ok(makeProgress({ section_id: "sec-1", scroll_pos: 0.8 })),
    );
    mockedGetSection.mockImplementation((id: string) => Promise.resolve(ok(makeSectionDetail(id))));

    render(<CourseReaderClient courseId="course-1" />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /deep dive/i })).toHaveAttribute(
        "aria-current",
        "true",
      ),
    );
  });
});
