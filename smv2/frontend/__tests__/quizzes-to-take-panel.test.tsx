import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import QuizzesToTakePanel from "@/components/dashboard/QuizzesToTakePanel";
import { listChapters, type ChapterOut, type CourseOut } from "@/lib/api/client";

import { ok } from "./support/api-result";

// Only the network boundary is mocked — deriveQuizItems runs for real so
// the test also exercises the not_attempted/retake classification.
vi.mock("@/lib/api/client", () => ({
  listChapters: vi.fn(),
}));

const mockedListChapters = vi.mocked(listChapters);

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

// Real ChapterOut shape. A never-attempted chapter comes back with
// test_stats: null (see quizzes.ts); an attempted one carries the aggregate.
function chapter(label: string | null, attempts: number, best: number | null): ChapterOut {
  return {
    chapter_label: label,
    section_ids: [],
    practice_section_ids: [],
    answers_section_ids: [],
    test_stats:
      attempts === 0 && best === null
        ? null
        : { attempts, best_score: best, latest_score: best },
  };
}

describe("QuizzesToTakePanel", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders a card per derived item with the right badge, and reports its count", async () => {
    mockedListChapters.mockResolvedValue(ok([chapter("Ch 1", 0, null), chapter("Ch 2", 2, 0.4)]));
    const onCount = vi.fn();

    render(
      <QuizzesToTakePanel
        courses={[makeCourse({ id: "c1", title: "Course One" })]}
        onCount={onCount}
      />,
    );

    expect(await screen.findByText("Ch 1")).toBeInTheDocument();
    expect(screen.getByText("Ch 2")).toBeInTheDocument();
    expect(screen.getByText("Not attempted")).toBeInTheDocument();
    // best_score is a 0–1 fraction; the badge must render it as a percentage
    // (0.4 → 40%), never the raw "0.4".
    expect(screen.getByText(/Retake · best 40%/)).toBeInTheDocument();
    expect(screen.queryByText(/best 0\.4/)).not.toBeInTheDocument();
    await waitFor(() => expect(onCount).toHaveBeenLastCalledWith(2));
  });

  it("links each card to that chapter's test page", async () => {
    mockedListChapters.mockResolvedValue(ok([chapter("Ch 1", 0, null)]));

    render(<QuizzesToTakePanel courses={[makeCourse({ id: "c1" })]} />);

    const link = await screen.findByRole("link", { name: /Ch 1/i });
    expect(link).toHaveAttribute("href", "/course/c1/chapter/Ch%201/test");
  });

  it("renders nothing when no chapter needs a quiz (quiet panel)", async () => {
    // Fully passed: attempted, best score above the retake threshold.
    mockedListChapters.mockResolvedValue(ok([chapter("Ch 1", 2, 0.95)]));
    const onCount = vi.fn();

    render(<QuizzesToTakePanel courses={[makeCourse({ id: "c1" })]} onCount={onCount} />);

    await waitFor(() => expect(onCount).toHaveBeenCalledWith(0));
    expect(screen.queryByRole("heading", { name: /quizzes to take/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Ch 1")).not.toBeInTheDocument();
  });

  it("only fetches chapters for ready courses", async () => {
    mockedListChapters.mockResolvedValue(ok([]));

    render(
      <QuizzesToTakePanel
        courses={[
          makeCourse({ id: "draft-course", status: "draft" }),
          makeCourse({ id: "ready-course", status: "ready" }),
        ]}
        onCount={vi.fn()}
      />,
    );

    await waitFor(() => expect(mockedListChapters).toHaveBeenCalledWith("ready-course"));
    expect(mockedListChapters).not.toHaveBeenCalledWith("draft-course");
  });
});
