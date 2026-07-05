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
    lesson_status: "not_started",
    has_content: true,
    word_count: 100,
    ...overrides,
  };
}

const COURSE: CourseOut = {
  id: "course-1",
  title: "Distributed Systems",
  status: "ready",
  section_count: 4,
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

    expect(screen.getByRole("link")).toHaveAttribute("href", "/course/course-1");
    expect(screen.getByText("Distributed Systems")).toBeInTheDocument();
  });

  it("shows the resumed chapter's title and percent complete once sections load", async () => {
    render(<ContinueCard course={COURSE} />);

    // sec-2 is order_index 1 of 4 sections -> (1+1)/4 = 50%
    expect(await screen.findByText(/time and ordering/i)).toBeInTheDocument();
    expect(screen.getByText(/50% complete/)).toBeInTheDocument();
  });
});
