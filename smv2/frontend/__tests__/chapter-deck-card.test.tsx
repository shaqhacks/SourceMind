import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ChapterDeckCard from "@/components/flashcards/ChapterDeckCard";

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  findActiveCardsJob: vi.fn(),
  generateCards: vi.fn(),
  getJob: vi.fn(),
}));

describe("ChapterDeckCard", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows a no-content message and no Generate button for a chapter with no content sections", () => {
    render(
      <ChapterDeckCard
        courseId="course-1"
        chapterNumber={1}
        title="Front Matter Only"
        sectionIds={[]}
        cards={[]}
        dueCount={0}
        isBrowsed={false}
        onBrowse={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/this chapter has no content section to generate cards from/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /generate cards/i })).not.toBeInTheDocument();
  });
});
