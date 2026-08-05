import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import StudyNextList from "@/components/dashboard/StudyNextList";
import { getStudyNext, type StudyNextItemOut } from "@/lib/api/client";

import { ok } from "./support/api-result";

vi.mock("@/lib/api/client", () => ({
  getStudyNext: vi.fn(),
}));

const mockedGetStudyNext = vi.mocked(getStudyNext);

describe("StudyNextList", () => {
  beforeEach(() => {
    mockedGetStudyNext.mockResolvedValue(ok([]));
  });

  it("labels new-card availability as new material", async () => {
    const suggestions: StudyNextItemOut[] = [
      {
        chapter_label: "Chapter 1",
        reason: "new_cards",
        detail: { overdue_count: 0, new_count: 6, available_count: 6 },
      },
    ];
    mockedGetStudyNext.mockResolvedValue(ok(suggestions));

    render(<StudyNextList courseId="course-1" />);

    expect(await screen.findByText("6 new cards")).toBeInTheDocument();
    expect(screen.queryByText(/overdue/i)).not.toBeInTheDocument();
  });

  it("labels due-card availability as overdue material", async () => {
    const suggestions: StudyNextItemOut[] = [
      {
        chapter_label: "Chapter 2",
        reason: "due_cards",
        detail: { overdue_count: 4, new_count: 0, available_count: 4 },
      },
    ];
    mockedGetStudyNext.mockResolvedValue(ok(suggestions));

    render(<StudyNextList courseId="course-1" />);

    expect(await screen.findByText("4 overdue cards")).toBeInTheDocument();
  });

  it("preserves mixed overdue and new-card detail", async () => {
    const suggestions: StudyNextItemOut[] = [
      {
        chapter_label: "Chapter 3",
        reason: "due_cards",
        detail: { overdue_count: 3, new_count: 4, available_count: 7 },
      },
    ];
    mockedGetStudyNext.mockResolvedValue(ok(suggestions));

    render(<StudyNextList courseId="course-1" />);

    expect(await screen.findByText("3 overdue · 4 new")).toBeInTheDocument();
  });
});
