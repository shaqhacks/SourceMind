import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Home from "@/app/page";
import {
  deleteCourse,
  findActiveIngestJob,
  findLatestIngestJob,
  getReviewSummary,
  getSkillMap,
  getStudyNext,
  listAssets,
  listChapters,
  listCourses,
  listSections,
  type CourseOut,
  type SectionOut,
  type SkillMapOut,
} from "@/lib/api/client";

import { err, ok } from "./support/api-result";

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  usePathname: () => "/",
}));

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  listCourses: vi.fn(),
  deleteCourse: vi.fn(),
  exportCourseUrl: (courseId: string) => `http://localhost:8000/api/courses/${courseId}/export`,
  findActiveIngestJob: vi.fn(),
  findLatestIngestJob: vi.fn(),
  listAssets: vi.fn(),
  startIngest: vi.fn(),
  listSections: vi.fn(),
  listChapters: vi.fn(),
  createCourse: vi.fn(),
  uploadAsset: vi.fn(),
  editOutline: vi.fn(),
  getJob: vi.fn(),
  getReviewSummary: vi.fn(),
  getStudyNext: vi.fn(),
  getSkillMap: vi.fn(),
}));

const mockedListCourses = vi.mocked(listCourses);
const mockedDeleteCourse = vi.mocked(deleteCourse);
const mockedFindActiveIngestJob = vi.mocked(findActiveIngestJob);
const mockedFindLatestIngestJob = vi.mocked(findLatestIngestJob);
const mockedListAssets = vi.mocked(listAssets);
const mockedListSections = vi.mocked(listSections);
const mockedListChapters = vi.mocked(listChapters);
const mockedGetReviewSummary = vi.mocked(getReviewSummary);
const mockedGetStudyNext = vi.mocked(getStudyNext);
const mockedGetSkillMap = vi.mocked(getSkillMap);

function makeCourse(overrides: Partial<CourseOut> = {}): CourseOut {
  return {
    id: "course-1",
    title: "Distributed Systems",
    status: "ready",
    section_count: 4,
    failed_asset_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    progress: null,
    ...overrides,
  };
}

function makeSection(overrides: Partial<SectionOut> = {}): SectionOut {
  return {
    id: "sec-0",
    asset_id: null,
    chapter_label: null,
    has_content: true,
    kind: "content",
    lesson_status: "none",
    order_index: 0,
    page_end: null,
    page_start: null,
    title: "Section",
    word_count: 100,
    ...overrides,
  };
}

function pdfFile(name: string): File {
  return new File(["%PDF-1.4 fake"], name, { type: "application/pdf" });
}

// Four content sections, saved progress sitting on the second one — gives
// useContinueChapter a real {title, percent} to derive (50%).
const CONTENT_SECTIONS: SectionOut[] = [
  makeSection({ id: "sec-0", order_index: 0, title: "Introduction" }),
  makeSection({ id: "sec-1", order_index: 1, title: "Loops and recursion" }),
  makeSection({ id: "sec-2", order_index: 2, title: "Trees" }),
  makeSection({ id: "sec-3", order_index: 3, title: "Graphs" }),
];

describe("Home page", () => {
  beforeEach(() => {
    mockedFindActiveIngestJob.mockResolvedValue(null);
    mockedFindLatestIngestJob.mockResolvedValue(null);
    mockedListAssets.mockResolvedValue(ok([]));
    mockedDeleteCourse.mockResolvedValue(ok(undefined));
    mockedListSections.mockResolvedValue(ok([]));
    mockedListChapters.mockResolvedValue(ok([]));
    mockedGetReviewSummary.mockResolvedValue(
      ok({ courses: [], due_total: 0, daily_throughput: 0, backlog_warning: false }),
    );
    mockedGetStudyNext.mockResolvedValue(ok([]));
    mockedGetSkillMap.mockResolvedValue(ok({ nodes: [], edges: [] }));
  });

  afterEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("shows the empty-state hero when there are no courses", async () => {
    mockedListCourses.mockResolvedValue(ok([]));
    render(<Home />);

    expect(await screen.findByText(/drop a pdf anywhere to start/i)).toBeInTheDocument();
  });

  it("shows a retryable error banner when loading courses fails", async () => {
    mockedListCourses.mockResolvedValue(err(500));
    render(<Home />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/loading courses failed/i);

    mockedListCourses.mockResolvedValue(ok([]));
    await userEvent.setup().click(screen.getByRole("button", { name: /retry/i }));

    expect(await screen.findByText(/drop a pdf anywhere to start/i)).toBeInTheDocument();
  });

  it("shows the heading and renders a course card for each course", async () => {
    mockedListCourses.mockResolvedValue(
      ok([
        makeCourse({ id: "a", title: "Distributed Systems" }),
        makeCourse({ id: "b", title: "Compilers", status: "draft" }),
      ]),
    );
    render(<Home />);

    expect(await screen.findByRole("heading", { name: /today's study plan/i })).toBeInTheDocument();
    expect(await screen.findByText("Distributed Systems")).toBeInTheDocument();
    expect(screen.getByText("Compilers")).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });

  it("a ready course's title is a real link into its reader (every card must be reachable, not just a task card)", async () => {
    mockedListCourses.mockResolvedValue(
      ok([
        makeCourse({ id: "a", title: "Distributed Systems" }),
        makeCourse({ id: "b", title: "Not Ready Yet", status: "draft" }),
      ]),
    );
    render(<Home />);

    const link = await screen.findByRole("link", { name: "Distributed Systems" });
    expect(link).toHaveAttribute("href", "/course/a");
    // A course with nothing to read yet has no link — just its plain title.
    expect(screen.queryByRole("link", { name: "Not Ready Yet" })).not.toBeInTheDocument();
  });

  describe("today's task cards", () => {
    it("shows a continue-reading task card with a progress bar for the most-recently-read course", async () => {
      mockedListCourses.mockResolvedValue(
        ok([
          makeCourse({
            id: "a",
            title: "Older Progress",
            progress: { section_id: "sec-1", scroll_pos: 0.1, updated_at: "2026-01-01T00:00:00Z" },
          }),
          makeCourse({
            id: "b",
            title: "Newer Progress",
            progress: { section_id: "sec-1", scroll_pos: 0.9, updated_at: "2026-01-10T00:00:00Z" },
          }),
        ]),
      );
      mockedListSections.mockResolvedValue(ok(CONTENT_SECTIONS));
      render(<Home />);

      expect(await screen.findByText(/keep reading — loops and recursion/i)).toBeInTheDocument();
      expect(screen.getByText(/newer progress · 50% through/i)).toBeInTheDocument();
      // SkillSnapshotCard renders its own progressbars (mastery bars) —
      // target the task card's specifically by its aria-label (= card title).
      expect(
        screen.getByRole("progressbar", { name: /keep reading — loops and recursion/i }),
      ).toHaveAttribute("aria-valuenow", "50");

      await userEvent.setup().click(screen.getByRole("button", { name: /resume/i }));
      expect(mockPush).toHaveBeenCalledWith("/course/b");
    });

    it("shows no continue-reading card when no course has saved progress", async () => {
      mockedListCourses.mockResolvedValue(ok([makeCourse({ id: "a", progress: null })]));
      render(<Home />);

      await screen.findByText("Distributed Systems");
      expect(screen.queryByText(/keep reading/i)).not.toBeInTheDocument();
    });

    it("shows a review task card linking straight into a due-now session when the primary course has cards due", async () => {
      mockedListCourses.mockResolvedValue(
        ok([
          makeCourse({
            id: "a",
            progress: { section_id: "sec-1", scroll_pos: 0.5, updated_at: "2026-01-01T00:00:00Z" },
          }),
        ]),
      );
      mockedGetReviewSummary.mockResolvedValue(
        ok({
          courses: [{ course_id: "a", title: "Distributed Systems", due_count: 7, new_count: 2 }],
          due_total: 7,
          daily_throughput: 3,
          backlog_warning: false,
        }),
      );
      render(<Home />);

      expect(await screen.findByText(/review 7 due flashcards/i)).toBeInTheDocument();
      await userEvent.setup().click(screen.getByRole("button", { name: /start review/i }));
      expect(mockPush).toHaveBeenCalledWith("/review?course=a&start=due");
    });

    it("hides the review task card when nothing is due anywhere", async () => {
      mockedListCourses.mockResolvedValue(ok([makeCourse({ id: "a", progress: null })]));
      render(<Home />);

      await screen.findByText("Distributed Systems");
      expect(screen.queryByText(/review .* due flashcard/i)).not.toBeInTheDocument();
    });

    it("shows a retake-test task card for the primary course's weakest chapter", async () => {
      mockedListCourses.mockResolvedValue(
        ok([
          makeCourse({
            id: "a",
            progress: { section_id: "sec-1", scroll_pos: 0.5, updated_at: "2026-01-01T00:00:00Z" },
          }),
        ]),
      );
      mockedGetStudyNext.mockResolvedValue(
        ok([{ chapter_label: "Chapter 1", reason: "low_test_score", detail: { best_score: 0.4 } }]),
      );
      render(<Home />);

      expect(await screen.findByText(/beat your 40% on chapter 1/i)).toBeInTheDocument();
      await userEvent.setup().click(screen.getByRole("button", { name: /retake test/i }));
      expect(mockPush).toHaveBeenCalledWith("/course/a/chapter/Chapter%201/test");
    });

    it("shows an empty task-list message when nothing applies", async () => {
      mockedListCourses.mockResolvedValue(ok([makeCourse({ id: "a", progress: null })]));
      render(<Home />);

      expect(await screen.findByText(/nothing on today's plan/i)).toBeInTheDocument();
    });
  });

  describe("skill snapshot", () => {
    const STRUGGLING_MAP: SkillMapOut = {
      nodes: [
        { id: "tokenization", slug: "tokenization", label: "Tokenization basics", level: 1, mastery: 86, status: "solid", blocked: false, unlock_note: null },
        { id: "token-counting", slug: "token-counting", label: "Token counting", level: 1, mastery: 31, status: "struggling", blocked: false, unlock_note: null },
        { id: "cost-estimation", slug: "cost-estimation", label: "Cost estimation", level: 2, mastery: 24, status: "struggling", blocked: true, unlock_note: null },
      ],
      edges: [{ from_id: "token-counting", to_id: "cost-estimation", kind: "weak" }],
    };

    it("renders the top skills and a data-driven 'why you're stuck' callout", async () => {
      mockedListCourses.mockResolvedValue(ok([makeCourse({ id: "a" })]));
      mockedGetSkillMap.mockResolvedValue(ok(STRUGGLING_MAP));

      render(<Home />);

      expect(await screen.findByText(/skill snapshot/i)).toBeInTheDocument();
      expect(screen.getByText("Tokenization basics")).toBeInTheDocument();
      // getAllByText (not getByText): "Token counting" also appears a
      // second time, as the weak prereq's own <strong> in the callout below.
      expect(screen.getAllByText("Token counting").length).toBeGreaterThan(0);
      expect(screen.getByText("Cost estimation")).toBeInTheDocument();

      expect(screen.getByText(/why you're stuck/i)).toBeInTheDocument();
      expect(screen.getByText(/24 mastery · requires Token counting/)).toBeInTheDocument();

      const link = screen.getByRole("link", { name: /full map/i });
      expect(link).toHaveAttribute("href", "/course/a/skills");

      await userEvent.setup().click(screen.getByRole("button", { name: /review the prerequisite/i }));
      expect(mockPush).toHaveBeenCalledWith("/course/a/skills/token-counting");
    });

    it("renders nothing when the course has no skill graph yet", async () => {
      mockedListCourses.mockResolvedValue(ok([makeCourse({ id: "a" })]));
      mockedGetSkillMap.mockResolvedValue(ok({ nodes: [], edges: [] }));

      render(<Home />);

      await screen.findByText("Distributed Systems");
      expect(screen.queryByText(/skill snapshot/i)).not.toBeInTheDocument();
    });

    it("renders nothing when the skill map fails to load", async () => {
      mockedListCourses.mockResolvedValue(ok([makeCourse({ id: "a" })]));
      mockedGetSkillMap.mockResolvedValue(err(500));

      render(<Home />);

      await screen.findByText("Distributed Systems");
      expect(screen.queryByText(/skill snapshot/i)).not.toBeInTheDocument();
    });
  });

  it("shows the This week day tiles", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse({ id: "a" })]));
    render(<Home />);

    await screen.findByText(/this week/i);
    expect(screen.getAllByText("M").length).toBeGreaterThan(0);
    expect(screen.getAllByText("S").length).toBe(2);
  });

  it("shows the stat trio derived from real course/review data", async () => {
    mockedListCourses.mockResolvedValue(
      ok([
        makeCourse({
          id: "a",
          progress: { section_id: "sec-1", scroll_pos: 0.5, updated_at: "2026-01-01T00:00:00Z" },
        }),
      ]),
    );
    mockedListSections.mockResolvedValue(ok(CONTENT_SECTIONS));
    mockedGetReviewSummary.mockResolvedValue(
      ok({
        courses: [{ course_id: "a", title: "Distributed Systems", due_count: 5, new_count: 1 }],
        due_total: 5,
        daily_throughput: 2.6,
        backlog_warning: false,
      }),
    );
    render(<Home />);

    expect(await screen.findByText("50%")).toBeInTheDocument();
    expect(screen.getByText("course progress")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("cards due")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument(); // Math.round(2.6)
    expect(screen.getByText(/cards\/day/i)).toBeInTheDocument();
  });

  it("deleting a course via its card removes it from the grid", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse({ id: "a", title: "Distributed Systems" })]));
    const user = userEvent.setup();
    render(<Home />);

    await screen.findByText("Distributed Systems");
    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    await user.click(screen.getByRole("button", { name: /confirm/i }));

    expect(mockedDeleteCourse).toHaveBeenCalledWith("a");
    await waitFor(() => expect(screen.queryByText("Distributed Systems")).not.toBeInTheDocument());
  });

  it("opens the upload flow after choosing files via the Start a new course button", async () => {
    mockedListCourses.mockResolvedValue(ok([]));
    render(<Home />);
    await screen.findByText(/drop a pdf anywhere to start/i);

    const input = screen.getByLabelText(/start a new course/i) as HTMLInputElement;
    await userEvent.setup().upload(input, pdfFile("book.pdf"));

    expect(screen.getByRole("dialog", { name: /start a new course/i })).toBeInTheDocument();
  });

  it("opens the upload flow when PDFs are dropped anywhere on the dashboard", async () => {
    mockedListCourses.mockResolvedValue(ok([]));
    const { container } = render(<Home />);
    await screen.findByText(/drop a pdf anywhere to start/i);

    const dropTarget = container.firstChild as HTMLElement;
    const file = pdfFile("dropped.pdf");
    fireEvent.drop(dropTarget, { dataTransfer: { files: [file], types: ["Files"] } });

    expect(await screen.findByRole("dialog", { name: /start a new course/i })).toBeInTheDocument();
  });

  it("ignores non-PDF files dropped on the dashboard", async () => {
    mockedListCourses.mockResolvedValue(ok([]));
    const { container } = render(<Home />);
    await screen.findByText(/drop a pdf anywhere to start/i);

    const dropTarget = container.firstChild as HTMLElement;
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    fireEvent.drop(dropTarget, { dataTransfer: { files: [file], types: ["Files"] } });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  describe("sample course hint", () => {
    it("shows the hint when exactly one course exists and it's ready", async () => {
      mockedListCourses.mockResolvedValue(
        ok([makeCourse({ id: "a", title: "Welcome to SourceMind", status: "ready" })]),
      );

      render(<Home />);

      expect(
        await screen.findByText(/this is a sample course — drop any pdf to create your own/i),
      ).toBeInTheDocument();
    });

    it("shows the hint while the single course is still ingesting", async () => {
      mockedListCourses.mockResolvedValue(ok([makeCourse({ id: "a", status: "ingesting" })]));

      render(<Home />);

      expect(await screen.findByText(/this is a sample course/i)).toBeInTheDocument();
    });

    it("does not show the hint when more than one course exists", async () => {
      mockedListCourses.mockResolvedValue(
        ok([makeCourse({ id: "a" }), makeCourse({ id: "b", title: "Second course" })]),
      );

      render(<Home />);
      await screen.findByText("Second course");

      expect(screen.queryByText(/this is a sample course/i)).not.toBeInTheDocument();
    });

    it("does not show the hint for a draft or failed single course", async () => {
      mockedListCourses.mockResolvedValue(ok([makeCourse({ id: "a", status: "draft" })]));

      render(<Home />);
      await screen.findByText("Distributed Systems");

      expect(screen.queryByText(/this is a sample course/i)).not.toBeInTheDocument();
    });

    it("dismissing hides it and persists the choice across remounts", async () => {
      mockedListCourses.mockResolvedValue(ok([makeCourse({ id: "a", status: "ready" })]));
      const user = userEvent.setup();

      const { unmount } = render(<Home />);
      await user.click(await screen.findByRole("button", { name: /dismiss hint/i }));
      expect(screen.queryByText(/this is a sample course/i)).not.toBeInTheDocument();
      unmount();

      render(<Home />);
      await screen.findByText("Distributed Systems");
      expect(screen.queryByText(/this is a sample course/i)).not.toBeInTheDocument();
    });
  });
});
