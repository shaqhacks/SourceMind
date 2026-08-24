import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CourseHomeClient from "@/components/course/CourseHomeClient";
import {
  getCourse,
  getReviewSummary,
  type CourseOut,
  type ReviewSummaryOut,
} from "@/lib/api/client";

import { ok } from "./support/api-result";

vi.mock("next/navigation", () => ({
  usePathname: () => "/course/course-1",
}));

vi.mock("@/lib/api/client", () => ({
  getCourse: vi.fn(),
  getReviewSummary: vi.fn(),
}));

const mockedGetCourse = vi.mocked(getCourse);
const mockedGetReviewSummary = vi.mocked(getReviewSummary);

const COURSE: CourseOut = {
  id: "course-1",
  title: "Distributed Systems",
  status: "ready",
  section_count: 4,
  failed_asset_count: 0,
  is_sample: false,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  progress: { section_id: "sec-2", scroll_pos: 0.4, updated_at: "2026-01-05T00:00:00Z" },
};

const SUMMARY: ReviewSummaryOut = {
  backlog_warning: false,
  due_total: 3,
  daily_throughput: 0,
  courses: [
    {
      course_id: "course-1",
      title: "Distributed Systems",
      overdue_count: 3,
      due_count: 3,
      available_count: 0,
      needs_attention_count: 0,
      new_count: 0,
      total_count: 10,
    },
  ],
};

describe("CourseHomeClient", () => {
  beforeEach(() => {
    mockedGetCourse.mockResolvedValue(ok(COURSE));
    mockedGetReviewSummary.mockResolvedValue(ok(SUMMARY));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders the course title and links to lessons, flashcards, skill map, and tests", async () => {
    render(<CourseHomeClient courseId="course-1" />);

    expect(await screen.findByRole("heading", { name: "Distributed Systems" })).toBeInTheDocument();

    expect(screen.getByRole("link", { name: /lessons/i })).toHaveAttribute(
      "href",
      "/course/course-1/read",
    );
    expect(screen.getByRole("link", { name: /flashcards/i })).toHaveAttribute(
      "href",
      "/review?course=course-1&scope=all",
    );
    expect(screen.getByRole("link", { name: /skill map/i })).toHaveAttribute(
      "href",
      "/course/course-1/skills",
    );
    expect(screen.getByRole("link", { name: /tests/i })).toHaveAttribute(
      "href",
      "/tests?course=course-1",
    );
  });

  it("surfaces the course's due-card count on the flashcards card", async () => {
    render(<CourseHomeClient courseId="course-1" />);

    expect(await screen.findByText(/3 cards due to review/i)).toBeInTheDocument();
  });
});
