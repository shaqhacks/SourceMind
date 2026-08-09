import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DueBadge from "@/components/DueBadge";
import { getReviewSummary, type ReviewSummaryOut } from "@/lib/api/client";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

import { ok } from "./support/api-result";

let mockPathname = "/";

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
}));

vi.mock("@/lib/api/client", () => ({
  getReviewSummary: vi.fn(),
}));

const mockedGetReviewSummary = vi.mocked(getReviewSummary);

function makeSummary(overrides: Partial<ReviewSummaryOut> = {}): ReviewSummaryOut {
  const dueTotal = overrides.due_total ?? 0;
  const courses =
    overrides.courses ??
    (dueTotal > 0
      ? [
          {
            course_id: "course-1",
            title: "Course One",
            due_count: dueTotal,
            overdue_count: dueTotal,
            new_count: 0,
            available_count: dueTotal,
            total_count: dueTotal,
            needs_attention_count: 0,
          },
        ]
      : []);
  return {
    due_total: dueTotal,
    daily_throughput: 0,
    backlog_warning: false,
    ...overrides,
    courses,
  };
}

describe("DueBadge", () => {
  beforeEach(() => {
    mockPathname = "/";
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders no link once loaded with zero due (but keeps the live region mounted)", async () => {
    mockedGetReviewSummary.mockResolvedValue(ok(makeSummary({ due_total: 0 })));

    render(<DueBadge />);
    await waitFor(() => expect(mockedGetReviewSummary).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows the due total as a link to /review", async () => {
    mockedGetReviewSummary.mockResolvedValue(ok(makeSummary({ due_total: 7 })));

    render(<DueBadge />);

    const link = await screen.findByRole("link", { name: /7 cards due/i });
    expect(link).toHaveAttribute("href", "/review");
  });

  it("refetches when the route changes", async () => {
    mockedGetReviewSummary
      .mockResolvedValueOnce(ok(makeSummary({ due_total: 3 })))
      .mockResolvedValueOnce(ok(makeSummary({ due_total: 5 })));

    const { rerender } = render(<DueBadge />);
    expect(await screen.findByText("3 cards due")).toBeInTheDocument();

    mockPathname = "/review";
    rerender(<DueBadge />);

    expect(await screen.findByText("5 cards due")).toBeInTheDocument();
    expect(mockedGetReviewSummary).toHaveBeenCalledTimes(2);
  });

  it("refetches when the review bus fires (a grade or a generation settled)", async () => {
    mockedGetReviewSummary
      .mockResolvedValueOnce(ok(makeSummary({ due_total: 2 })))
      .mockResolvedValueOnce(ok(makeSummary({ due_total: 1 })));

    render(<DueBadge />);
    expect(await screen.findByText("2 cards due")).toBeInTheDocument();

    notifyReviewSettled();

    expect(await screen.findByText("1 card due")).toBeInTheDocument();
  });

  it("is a stable aria-live region so a screen reader announces the count changing", async () => {
    mockedGetReviewSummary.mockResolvedValue(ok(makeSummary({ due_total: 4 })));

    const { container } = render(<DueBadge />);
    await screen.findByText("4 cards due");

    const liveRegion = container.querySelector('[aria-live="polite"]');
    expect(liveRegion).not.toBeNull();
    expect(liveRegion).toHaveAttribute("aria-atomic", "true");
  });
});
