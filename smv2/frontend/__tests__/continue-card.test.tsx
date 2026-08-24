import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ContinueCard from "@/components/dashboard/ContinueCard";
import { listSections, type CourseOut, type SectionOut } from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({
  listSections: vi.fn(),
}));

const mockedListSections = vi.mocked(listSections);

function makeSection(overrides: Partial<SectionOut> = {}): SectionOut {
  return {
    id: "sec-1",
    title: "Chapter",
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

describe("ContinueCard", () => {
  beforeEach(() => {
    mockedListSections.mockResolvedValue({
      status: 200,
      ok: true,
      data: [
        makeSection({ id: "sec-1", title: "Introduction", order_index: 0 }),
        makeSection({ id: "sec-2", title: "Time and Ordering", order_index: 1 }),
      ],
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("links to the course and shows its title immediately", () => {
    render(<ContinueCard course={COURSE} />);

    expect(screen.getByRole("link")).toHaveAttribute("href", "/course/course-1/read");
    expect(screen.getByText("Distributed Systems")).toBeInTheDocument();
  });

  it("shows the resumed chapter's title and percent complete once sections load", async () => {
    render(<ContinueCard course={COURSE} />);

    // Both mocked sections are content-kind: sec-2 is content-index 1 of 2 -> (1+1)/2 = 100%.
    // (course.section_count is no longer consulted — see the content-only test below.)
    expect(await screen.findByText(/time and ordering/i)).toBeInTheDocument();
    expect(screen.getByText(/100% complete/)).toBeInTheDocument();
  });

  it("measures percent complete against content sections only, ignoring practice/answers", async () => {
    mockedListSections.mockResolvedValue({
      status: 200,
      ok: true,
      data: [
        makeSection({ id: "sec-1", title: "Introduction", order_index: 0, kind: "content" }),
        makeSection({ id: "sec-2", title: "Time and Ordering", order_index: 1, kind: "content" }),
        makeSection({ id: "sec-practice", title: "Practice", order_index: 2, kind: "practice" }),
        makeSection({ id: "sec-3", title: "Consensus", order_index: 3, kind: "content" }),
      ],
    });

    render(<ContinueCard course={COURSE} />);

    // sec-2 is content-index 1 of 3 content sections -> (1+1)/3 = 67%; a
    // raw order_index/section_count count (1+1)/4 would understate it at 50%.
    expect(await screen.findByText(/time and ordering/i)).toBeInTheDocument();
    expect(screen.getByText(/67% complete/)).toBeInTheDocument();
  });
});
