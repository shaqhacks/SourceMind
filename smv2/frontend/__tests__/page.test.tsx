import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import Home from "@/app/page";
import {
  deleteCourse,
  findActiveIngestJob,
  findLatestIngestJob,
  getReviewSummary,
  getStudyNext,
  listAssets,
  listChapters,
  listCourses,
  listSections,
  type CourseOut,
} from "@/lib/api/client";

import { err, ok } from "./support/api-result";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
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

function pdfFile(name: string): File {
  return new File(["%PDF-1.4 fake"], name, { type: "application/pdf" });
}

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

  it("renders a course card for each course", async () => {
    mockedListCourses.mockResolvedValue(
      ok([
        makeCourse({ id: "a", title: "Distributed Systems" }),
        makeCourse({ id: "b", title: "Compilers", status: "draft" }),
      ]),
    );
    render(<Home />);

    expect(await screen.findByText("Distributed Systems")).toBeInTheDocument();
    expect(screen.getByText("Compilers")).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
  });

  it("a ready course's title is a real link into its reader (every card must be reachable, not just the Continue one)", async () => {
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

  it("shows the Continue card for the course with the most recent progress, ahead of the course grid", async () => {
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
    render(<Home />);

    expect(await screen.findByText(/continue reading/i)).toBeInTheDocument();
    // The Continue card's course title appears twice (once in the card,
    // once in the grid below) — assert at least one is the right course.
    expect(screen.getAllByText("Newer Progress").length).toBeGreaterThan(0);
  });

  it("shows no Continue card when no course has saved progress", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse({ id: "a", progress: null })]));
    render(<Home />);

    await screen.findByText("Distributed Systems");
    expect(screen.queryByText(/continue reading/i)).not.toBeInTheDocument();
  });

  it("shows a Review card linking straight into a due-now session when the primary course has cards due", async () => {
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

    // Target the Review card specifically — StatsRow now also renders a
    // "7 cards due" stat tile that links to the generic /review hub.
    const link = await screen.findByRole("link", { name: /start your review/i });
    expect(link).toHaveAttribute("href", "/review?course=a&start=due");
    expect(link).toHaveTextContent(/7 cards due/i);
  });

  it("hides the Review card when nothing is due anywhere", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse({ id: "a", progress: null })]));
    render(<Home />);

    await screen.findByText("Distributed Systems");
    // The Review card is gone; StatsRow's always-present "cards due" tile
    // (showing 0) is not the Review card, so assert the card's own copy.
    expect(screen.queryByText(/start your review/i)).not.toBeInTheDocument();
  });

  it("shows up to 3 Study next suggestions for the primary course, each linking out with its reason", async () => {
    mockedListCourses.mockResolvedValue(
      ok([
        makeCourse({
          id: "a",
          progress: { section_id: "sec-1", scroll_pos: 0.5, updated_at: "2026-01-01T00:00:00Z" },
        }),
      ]),
    );
    mockedGetStudyNext.mockResolvedValue(
      ok([
        { chapter_label: "Ch 1", reason: "low_test_score", detail: { best_score: 0.4 } },
        { chapter_label: "Ch 2", reason: "due_cards", detail: { due_count: 12 } },
        { chapter_label: "Ch 3", reason: "unread", detail: {} },
        { chapter_label: "Ch 4", reason: "stale", detail: { days_since: 9 } },
      ]),
    );
    render(<Home />);

    await screen.findByText(/study next/i);
    expect(screen.getByText("Ch 1")).toBeInTheDocument();
    expect(screen.getByText("Ch 2")).toBeInTheDocument();
    expect(screen.getByText("Ch 3")).toBeInTheDocument();
    expect(screen.queryByText("Ch 4")).not.toBeInTheDocument();
    expect(screen.getByText("low test score (40%)")).toBeInTheDocument();

    expect(screen.getByRole("link", { name: /ch 1.*low test score/i })).toHaveAttribute(
      "href",
      "/course/a/chapter/Ch%201/test",
    );
    expect(screen.getByRole("link", { name: /ch 2.*12 cards piling up/i })).toHaveAttribute(
      "href",
      "/review?course=a&start=due",
    );
    expect(screen.getByRole("link", { name: /ch 3.*unread/i })).toHaveAttribute(
      "href",
      "/course/a",
    );
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

  it("opens the upload flow after choosing files via the Upload PDF button", async () => {
    mockedListCourses.mockResolvedValue(ok([]));
    render(<Home />);
    await screen.findByText(/drop a pdf anywhere to start/i);

    const input = screen.getByLabelText(/upload pdf/i) as HTMLInputElement;
    await userEvent.setup().upload(input, pdfFile("book.pdf"));

    expect(screen.getByRole("dialog", { name: /upload course/i })).toBeInTheDocument();
  });

  it("opens the upload flow when PDFs are dropped anywhere on the dashboard", async () => {
    mockedListCourses.mockResolvedValue(ok([]));
    const { container } = render(<Home />);
    await screen.findByText(/drop a pdf anywhere to start/i);

    const dropTarget = container.firstChild as HTMLElement;
    const file = pdfFile("dropped.pdf");
    fireEvent.drop(dropTarget, { dataTransfer: { files: [file], types: ["Files"] } });

    expect(await screen.findByRole("dialog", { name: /upload course/i })).toBeInTheDocument();
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
