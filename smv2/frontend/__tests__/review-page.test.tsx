import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReviewPage from "@/app/review/page";
import {
  getReviewQueue,
  getReviewSummary,
  gradeCard,
  type ReviewQueueCardOut,
  type ReviewQueueOut,
  type ReviewSummaryOut,
} from "@/lib/api/client";

let mockSearchParams = new URLSearchParams();
const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => mockSearchParams,
  usePathname: () => "/review",
}));

vi.mock("@/lib/api/client", () => ({
  getReviewSummary: vi.fn(),
  getReviewQueue: vi.fn(),
  gradeCard: vi.fn(),
}));

const mockedGetReviewSummary = vi.mocked(getReviewSummary);
const mockedGetReviewQueue = vi.mocked(getReviewQueue);
const mockedGradeCard = vi.mocked(gradeCard);

function makeSummary(overrides: Partial<ReviewSummaryOut> = {}): ReviewSummaryOut {
  return {
    courses: [{ course_id: "course-1", title: "Intro to Testing", due_count: 5, new_count: 2 }],
    due_total: 7,
    daily_throughput: 3,
    backlog_warning: false,
    ...overrides,
  };
}

function makeQueue(overrides: Partial<ReviewQueueOut> = {}): ReviewQueueOut {
  return { cards: [], due: 5, new: 2, total: 7, ...overrides };
}

function makeQueueCard(overrides: Partial<ReviewQueueCardOut> = {}): ReviewQueueCardOut {
  return {
    id: "card-1",
    section_id: "sec-1",
    front_md: "What is 2+2?",
    back_md: "4",
    due_at: "2026-01-01T00:00:00Z",
    is_new: false,
    ...overrides,
  };
}

describe("ReviewPage", () => {
  beforeEach(() => {
    mockSearchParams = new URLSearchParams();
    mockedGradeCard.mockResolvedValue({
      status: 200,
      ok: true,
      data: { next_due_at: "2026-01-02T00:00:00Z", remaining_due: 0 },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("hub: shows the backlog warning and course list from review_summary", async () => {
    mockedGetReviewSummary.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeSummary({ backlog_warning: true, due_total: 40 }),
    });

    render(<ReviewPage />);

    expect(await screen.findByText(/40 due — more than 2 days at your pace/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /intro to testing/i })).toHaveTextContent(
      /5 due · 2 new/i,
    );
  });

  it("hub: shows a next-action empty state when nothing is due anywhere", async () => {
    mockedGetReviewSummary.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeSummary({ due_total: 0, courses: [] }),
    });

    render(<ReviewPage />);

    expect(await screen.findByText("No cards due")).toBeInTheDocument();
    expect(
      screen.getByText(/generate flashcards from a chapter, or keep reading/i),
    ).toBeInTheDocument();
  });

  it("hub: clicking a course navigates to its chooser via ?course=", async () => {
    mockedGetReviewSummary.mockResolvedValue({ status: 200, ok: true, data: makeSummary() });
    mockedGetReviewQueue.mockResolvedValue({ status: 200, ok: true, data: makeQueue() });
    const user = userEvent.setup();

    render(<ReviewPage />);

    await user.click(await screen.findByRole("button", { name: /intro to testing/i }));

    expect(mockPush).toHaveBeenCalledWith("/review?course=course-1");
    expect(await screen.findByText(/ready to review/i)).toBeInTheDocument();
  });

  it("chooser: offers 10 / 25 / all only when the total justifies them", async () => {
    mockSearchParams = new URLSearchParams({ course: "course-1" });
    mockedGetReviewQueue.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeQueue({ total: 30, due: 25, new: 5 }),
    });

    render(<ReviewPage />);

    expect(await screen.findByRole("button", { name: /^review 10$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^review 25$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /review all \(30\)/i })).toBeInTheDocument();
  });

  it("chooser: collapses to a single 'All (n)' option when the total is small", async () => {
    mockSearchParams = new URLSearchParams({ course: "course-1" });
    mockedGetReviewQueue.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeQueue({ total: 8, due: 6, new: 2 }),
    });

    render(<ReviewPage />);

    expect(await screen.findByRole("button", { name: /review all \(8\)/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^review 10$/i })).not.toBeInTheDocument();
  });

  it("chooser: shows the empty state when the course has nothing due", async () => {
    mockSearchParams = new URLSearchParams({ course: "course-1" });
    mockedGetReviewQueue.mockResolvedValue({ status: 200, ok: true, data: makeQueue({ total: 0 }) });

    render(<ReviewPage />);

    expect(await screen.findByText("No cards due")).toBeInTheDocument();
  });

  it("session: space reveals the back, grading keys 1-4 advance and capture elapsed_ms, and the summary tallies by grade", async () => {
    mockSearchParams = new URLSearchParams({ course: "course-1" });
    mockedGetReviewQueue
      .mockResolvedValueOnce({ status: 200, ok: true, data: makeQueue({ total: 2, due: 2 }) })
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        data: makeQueue({
          total: 2,
          cards: [
            makeQueueCard({ id: "card-1", front_md: "Q1", back_md: "A1" }),
            makeQueueCard({ id: "card-2", front_md: "Q2", back_md: "A2" }),
          ],
        }),
      });
    const user = userEvent.setup();

    render(<ReviewPage />);

    await user.click(await screen.findByRole("button", { name: /review all \(2\)/i }));

    expect(await screen.findByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByText("Q1")).toBeInTheDocument();
    expect(screen.queryByText("A1")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^again \(1\)$/i })).not.toBeInTheDocument();

    fireEvent.keyDown(window, { key: " " });
    expect(await screen.findByText("A1")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "3" });

    expect(mockedGradeCard).toHaveBeenCalledWith(
      "card-1",
      expect.objectContaining({ grade: 3, elapsed_ms: expect.any(Number) }),
    );

    expect(await screen.findByText("2 of 2")).toBeInTheDocument();
    expect(screen.getByText("Q2")).toBeInTheDocument();
    expect(screen.queryByText("A2")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /reveal/i }));
    await user.click(screen.getByRole("button", { name: /^easy \(4\)$/i }));

    expect(mockedGradeCard).toHaveBeenCalledWith(
      "card-2",
      expect.objectContaining({ grade: 4, elapsed_ms: expect.any(Number) }),
    );

    expect(await screen.findByText("Session complete")).toBeInTheDocument();
    const summary = screen.getByText("Session complete").closest("div");
    expect(summary).not.toBeNull();
    if (summary) {
      expect(within(summary).getByText(/good: 1/i)).toBeInTheDocument();
      expect(within(summary).getByText(/easy: 1/i)).toBeInTheDocument();
      expect(within(summary).getByText(/again: 0/i)).toBeInTheDocument();
      expect(within(summary).getByText(/hard: 0/i)).toBeInTheDocument();
    }
  });

  it("'?' opens the shortcuts overlay from any phase (e.g. the hub)", async () => {
    mockedGetReviewSummary.mockResolvedValue({ status: 200, ok: true, data: makeSummary() });

    render(<ReviewPage />);
    await screen.findByRole("button", { name: /intro to testing/i });

    fireEvent.keyDown(window, { key: "?" });

    expect(await screen.findByRole("dialog", { name: /keyboard shortcuts/i })).toBeInTheDocument();
  });
});
