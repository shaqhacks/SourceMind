import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CourseReaderClient from "@/components/reader/CourseReaderClient";
import {
  getCourse,
  getProgress,
  getSection,
  listSections,
  saveProgress,
  type CourseOut,
  type ProgressOut,
  type SectionOut,
} from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({
  getCourse: vi.fn(),
  listSections: vi.fn(),
  getProgress: vi.fn(),
  getSection: vi.fn(),
  saveProgress: vi.fn(),
}));

const mockedGetCourse = vi.mocked(getCourse);
const mockedListSections = vi.mocked(listSections);
const mockedGetProgress = vi.mocked(getProgress);
const mockedGetSection = vi.mocked(getSection);
const mockedSaveProgress = vi.mocked(saveProgress);

function makeCourse(overrides: Partial<CourseOut> = {}): CourseOut {
  return {
    id: "course-1",
    title: "Distributed Systems",
    status: "ready",
    section_count: 1,
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
    lesson_status: "not_started",
    has_content: true,
    word_count: 100,
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

describe("CourseReaderClient", () => {
  beforeEach(() => {
    mockedGetSection.mockResolvedValue({
      status: 200,
      ok: true,
      data: {
        id: "sec-1",
        course_id: "course-1",
        title: "Introduction",
        order_index: 0,
        page_start: 1,
        page_end: 5,
        body_md: "# Introduction\n\nBody text.",
        content_hash: "hash",
        lesson_md: null,
        lesson_status: "not_started",
        extractor_version: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    });
    mockedSaveProgress.mockResolvedValue({ status: 200, ok: true });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows a loading state before the fetches resolve", () => {
    mockedGetCourse.mockReturnValue(new Promise(() => {}));
    mockedListSections.mockReturnValue(new Promise(() => {}));
    mockedGetProgress.mockReturnValue(new Promise(() => {}));

    render(<CourseReaderClient courseId="course-1" />);

    expect(screen.getByText(/loading course/i)).toBeInTheDocument();
  });

  it("loads the course, its sections, and saved progress, then renders the reader", async () => {
    mockedGetCourse.mockResolvedValue({ status: 200, ok: true, data: makeCourse() });
    mockedListSections.mockResolvedValue({
      status: 200,
      ok: true,
      data: [makeSection()],
    });
    mockedGetProgress.mockResolvedValue({ status: 200, ok: true, data: makeProgress() });

    render(<CourseReaderClient courseId="course-1" />);

    expect(await screen.findByRole("heading", { level: 2, name: /introduction/i })).toBeInTheDocument();
    expect(mockedGetCourse).toHaveBeenCalledWith("course-1");
    expect(mockedListSections).toHaveBeenCalledWith("course-1");
    expect(mockedGetProgress).toHaveBeenCalledWith("course-1");
  });

  it("shows a retryable error banner when a fetch fails, and recovers on retry", async () => {
    mockedGetCourse.mockResolvedValueOnce({ status: 500, ok: false });
    mockedListSections.mockResolvedValue({ status: 200, ok: true, data: [makeSection()] });
    mockedGetProgress.mockResolvedValue({ status: 200, ok: true, data: makeProgress() });

    const user = userEvent.setup();
    render(<CourseReaderClient courseId="course-1" />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/loading course failed/i);

    mockedGetCourse.mockResolvedValue({ status: 200, ok: true, data: makeCourse() });
    await user.click(screen.getByRole("button", { name: /retry/i }));

    expect(
      await screen.findByRole("heading", { level: 2, name: /introduction/i }),
    ).toBeInTheDocument();
  });

  it("treats a network failure (no status) as retryable", async () => {
    mockedGetCourse.mockResolvedValue({ ok: false });
    mockedListSections.mockResolvedValue({ status: 200, ok: true, data: [] });
    mockedGetProgress.mockResolvedValue({ status: 200, ok: true, data: makeProgress() });

    render(<CourseReaderClient courseId="course-1" />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/could not reach the api/i);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("shows an empty-course message with a link back to the dashboard when there are no sections", async () => {
    mockedGetCourse.mockResolvedValue({ status: 200, ok: true, data: makeCourse() });
    mockedListSections.mockResolvedValue({ status: 200, ok: true, data: [] });
    mockedGetProgress.mockResolvedValue({ status: 200, ok: true, data: makeProgress() });

    render(<CourseReaderClient courseId="course-1" />);

    expect(await screen.findByText(/doesn.t have any chapters yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /dashboard/i })).toHaveAttribute("href", "/");
  });

  it("resumes at the saved section once loaded", async () => {
    mockedGetCourse.mockResolvedValue({ status: 200, ok: true, data: makeCourse() });
    mockedListSections.mockResolvedValue({
      status: 200,
      ok: true,
      data: [makeSection({ id: "sec-1", title: "Introduction" }), makeSection({ id: "sec-2", title: "Deep Dive", order_index: 1 })],
    });
    mockedGetProgress.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeProgress({ section_id: "sec-2", scroll_pos: 0.3 }),
    });
    mockedGetSection.mockImplementation((id: string) =>
      Promise.resolve({
        status: 200,
        ok: true,
        data: {
          id,
          course_id: "course-1",
          title: id === "sec-2" ? "Deep Dive" : "Introduction",
          order_index: id === "sec-2" ? 1 : 0,
          page_start: 1,
          page_end: 5,
          body_md: `Body for ${id}`,
          content_hash: "hash",
          lesson_md: null,
          lesson_status: "not_started",
          extractor_version: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      }),
    );

    render(<CourseReaderClient courseId="course-1" />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /deep dive/i })).toHaveAttribute(
        "aria-current",
        "true",
      ),
    );
  });
});
