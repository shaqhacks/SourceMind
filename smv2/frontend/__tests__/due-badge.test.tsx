import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DueBadge from "@/components/DueBadge";
import { getReviewSummary, type ReviewSummaryOut } from "@/lib/api/client";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

let mockPathname = "/";

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
}));

vi.mock("@/lib/api/client", () => ({
  getReviewSummary: vi.fn(),
}));

const mockedGetReviewSummary = vi.mocked(getReviewSummary);

function makeSummary(overrides: Partial<ReviewSummaryOut> = {}): ReviewSummaryOut {
  return {
    courses: [],
    due_total: 0,
    daily_throughput: 0,
    backlog_warning: false,
    ...overrides,
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
    mockedGetReviewSummary.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeSummary({ due_total: 0 }),
    });

    render(<DueBadge />);
    await waitFor(() => expect(mockedGetReviewSummary).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows the due total as a link to /review", async () => {
    mockedGetReviewSummary.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeSummary({ due_total: 7 }),
    });

    render(<DueBadge />);

    const link = await screen.findByRole("link", { name: /7 due/i });
    expect(link).toHaveAttribute("href", "/review");
  });

  it("refetches when the route changes", async () => {
    mockedGetReviewSummary
      .mockResolvedValueOnce({ status: 200, ok: true, data: makeSummary({ due_total: 3 }) })
      .mockResolvedValueOnce({ status: 200, ok: true, data: makeSummary({ due_total: 5 }) });

    const { rerender } = render(<DueBadge />);
    expect(await screen.findByText("3 due")).toBeInTheDocument();

    mockPathname = "/review";
    rerender(<DueBadge />);

    expect(await screen.findByText("5 due")).toBeInTheDocument();
    expect(mockedGetReviewSummary).toHaveBeenCalledTimes(2);
  });

  it("refetches when the review bus fires (a grade or a generation settled)", async () => {
    mockedGetReviewSummary
      .mockResolvedValueOnce({ status: 200, ok: true, data: makeSummary({ due_total: 2 }) })
      .mockResolvedValueOnce({ status: 200, ok: true, data: makeSummary({ due_total: 1 }) });

    render(<DueBadge />);
    expect(await screen.findByText("2 due")).toBeInTheDocument();

    notifyReviewSettled();

    expect(await screen.findByText("1 due")).toBeInTheDocument();
  });

  it("is a stable aria-live region so a screen reader announces the count changing", async () => {
    mockedGetReviewSummary.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeSummary({ due_total: 4 }),
    });

    const { container } = render(<DueBadge />);
    await screen.findByText("4 due");

    const liveRegion = container.querySelector('[aria-live="polite"]');
    expect(liveRegion).not.toBeNull();
    expect(liveRegion).toHaveAttribute("aria-atomic", "true");
  });
});
