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

import { ok } from "./support/api-result";

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
    mockedGradeCard.mockResolvedValue(ok({ next_due_at: "2026-01-02T00:00:00Z", remaining_due: 0 }));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("hub: shows the backlog warning and course list from review_summary", async () => {
    mockedGetReviewSummary.mockResolvedValue(ok(makeSummary({ backlog_warning: true, due_total: 40 })));

    render(<ReviewPage />);

    expect(await screen.findByText(/40 due — more than 2 days at your pace/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /intro to testing/i })).toHaveTextContent(
      /5 due · 2 new/i,
    );
  });

  it("hub: shows a next-action empty state when nothing is due anywhere", async () => {
    mockedGetReviewSummary.mockResolvedValue(ok(makeSummary({ due_total: 0, courses: [] })));

    render(<ReviewPage />);

    expect(await screen.findByText("All caught up")).toBeInTheDocument();
    expect(
      screen.getByText(/generate flashcards from a chapter, or keep reading/i),
    ).toBeInTheDocument();
  });

  it("hub: clicking a course navigates to its chooser via ?course=", async () => {
    mockedGetReviewSummary.mockResolvedValue(ok(makeSummary()));
    mockedGetReviewQueue.mockResolvedValue(ok(makeQueue()));
    const user = userEvent.setup();

    render(<ReviewPage />);

    await user.click(await screen.findByRole("button", { name: /intro to testing/i }));

    expect(mockPush).toHaveBeenCalledWith("/review?course=course-1");
    expect(await screen.findByText(/ready to review/i)).toBeInTheDocument();
  });

  it("chooser: offers 10 / 25 / all only when the total justifies them", async () => {
    mockSearchParams = new URLSearchParams({ course: "course-1" });
    mockedGetReviewQueue.mockResolvedValue(ok(makeQueue({ total: 30, due: 25, new: 5 })));

    render(<ReviewPage />);

    expect(await screen.findByRole("button", { name: /^review 10$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^review 25$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /review all \(30\)/i })).toBeInTheDocument();
  });

  it("chooser: collapses to a single 'All (n)' option when the total is small", async () => {
    mockSearchParams = new URLSearchParams({ course: "course-1" });
    mockedGetReviewQueue.mockResolvedValue(ok(makeQueue({ total: 8, due: 6, new: 2 })));

    render(<ReviewPage />);

    expect(await screen.findByRole("button", { name: /review all \(8\)/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^review 10$/i })).not.toBeInTheDocument();
  });

  it("chooser: shows the empty state when the course has nothing due", async () => {
    mockSearchParams = new URLSearchParams({ course: "course-1" });
    mockedGetReviewQueue.mockResolvedValue(ok(makeQueue({ total: 0 })));

    render(<ReviewPage />);

    expect(await screen.findByText("All caught up")).toBeInTheDocument();
  });

  it("session: space reveals the back, grading keys 1-4 advance and capture elapsed_ms, and the summary tallies by grade", async () => {
    mockSearchParams = new URLSearchParams({ course: "course-1" });
    mockedGetReviewQueue
      .mockResolvedValueOnce(ok(makeQueue({ total: 2, due: 2 })))
      .mockResolvedValueOnce(
        ok(
          makeQueue({
            total: 2,
            cards: [
              makeQueueCard({ id: "card-1", front_md: "Q1", back_md: "A1" }),
              makeQueueCard({ id: "card-2", front_md: "Q2", back_md: "A2" }),
            ],
          }),
        ),
      );
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
    mockedGetReviewSummary.mockResolvedValue(ok(makeSummary()));

    render(<ReviewPage />);
    await screen.findByRole("button", { name: /intro to testing/i });

    fireEvent.keyDown(window, { key: "?" });

    expect(await screen.findByRole("dialog", { name: /keyboard shortcuts/i })).toBeInTheDocument();
  });

  describe("session resume", () => {
    const STORAGE_KEY = "smv2.review.session";

    function fiveCards() {
      return [1, 2, 3, 4, 5].map((n) =>
        makeQueueCard({ id: `card-${n}`, front_md: `Q${n}`, back_md: `A${n}` }),
      );
    }

    it("grading 2 of 5, unmounting, and remounting resumes at card 3 with the tally intact", async () => {
      mockSearchParams = new URLSearchParams({ course: "course-1" });
      const allFive = fiveCards();
      mockedGetReviewQueue
        .mockResolvedValueOnce(ok(makeQueue({ total: 5, due: 5 }))) // chooser
        .mockResolvedValueOnce(ok(makeQueue({ total: 5, cards: allFive }))); // session start

      const { unmount } = render(<ReviewPage />);
      await userEvent.setup().click(await screen.findByRole("button", { name: /review all \(5\)/i }));

      await screen.findByText("1 of 5");
      fireEvent.keyDown(window, { key: " " });
      fireEvent.keyDown(window, { key: "3" }); // grade card 1: Good
      await screen.findByText("2 of 5");
      fireEvent.keyDown(window, { key: " " });
      fireEvent.keyDown(window, { key: "2" }); // grade card 2: Hard

      await screen.findByText("3 of 5");
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
      expect(stored).toMatchObject({
        courseId: "course-1",
        chosenSize: 5,
        remainingCardIds: ["card-3", "card-4", "card-5"],
        gradedTally: { 3: 1, 2: 1 },
      });

      unmount();

      // Backend has already dropped the two graded cards from the due queue.
      mockedGetReviewQueue.mockResolvedValueOnce(
        ok(makeQueue({ total: 3, cards: allFive.slice(2) })),
      );

      render(<ReviewPage />);

      expect(await screen.findByText(/resumed session — 3 left/i)).toBeInTheDocument();
      expect(await screen.findByText("1 of 3")).toBeInTheDocument();
      expect(screen.getByText("Q3")).toBeInTheDocument();

      fireEvent.keyDown(window, { key: " " });
      fireEvent.keyDown(window, { key: "1" }); // grade card 3: Again

      const storedAfterResumeGrade = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
      expect(storedAfterResumeGrade).toMatchObject({
        remainingCardIds: ["card-4", "card-5"],
        gradedTally: { 3: 1, 2: 1, 1: 1 },
      });
    });

    it("completing a session clears the stored session", async () => {
      mockSearchParams = new URLSearchParams({ course: "course-1" });
      mockedGetReviewQueue
        .mockResolvedValueOnce(ok(makeQueue({ total: 2, due: 2 })))
        .mockResolvedValueOnce(
          ok(
            makeQueue({
              total: 2,
              cards: [
                makeQueueCard({ id: "card-1", front_md: "Q1", back_md: "A1" }),
                makeQueueCard({ id: "card-2", front_md: "Q2", back_md: "A2" }),
              ],
            }),
          ),
        );

      render(<ReviewPage />);
      await userEvent.setup().click(await screen.findByRole("button", { name: /review all \(2\)/i }));

      await screen.findByText("1 of 2");
      fireEvent.keyDown(window, { key: " " });
      fireEvent.keyDown(window, { key: "3" });
      await screen.findByText("2 of 2");
      expect(localStorage.getItem(STORAGE_KEY)).not.toBeNull();

      fireEvent.keyDown(window, { key: " " });
      fireEvent.keyDown(window, { key: "3" });

      await screen.findByText("Session complete");
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });

    it("discarding a resumed session clears storage and returns to the chooser", async () => {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          courseId: "course-1",
          chosenSize: 5,
          remainingCardIds: ["card-3", "card-4", "card-5"],
          gradedTally: { 3: 1, 2: 1 },
          startedAt: Date.now(),
        }),
      );
      mockedGetReviewQueue
        .mockResolvedValueOnce(ok(makeQueue({ total: 3, cards: fiveCards().slice(2) }))) // reconcile
        .mockResolvedValueOnce(ok(makeQueue({ total: 3, due: 3 }))); // chooser, after discard

      render(<ReviewPage />);

      expect(await screen.findByText(/resumed session — 3 left/i)).toBeInTheDocument();
      await userEvent.setup().click(screen.getByRole("button", { name: /discard/i }));

      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
      expect(await screen.findByText(/ready to review/i)).toBeInTheDocument();
      expect(screen.queryByText(/resumed session/i)).not.toBeInTheDocument();
    });
  });

  describe("?start=due bootstrap", () => {
    const STORAGE_KEY = "smv2.review.session";

    it("skips the hub/chooser entirely and lands directly in a session sized to what's due now", async () => {
      mockSearchParams = new URLSearchParams({ course: "course-1", start: "due" });
      mockedGetReviewQueue
        .mockResolvedValueOnce(ok(makeQueue({ due: 3, new: 1, total: 10 }))) // due-count lookup
        .mockResolvedValueOnce(
          ok(
            makeQueue({
              due: 3,
              cards: [1, 2, 3].map((n) =>
                makeQueueCard({ id: `card-${n}`, front_md: `Q${n}`, back_md: `A${n}` }),
              ),
            }),
          ),
        );

      render(<ReviewPage />);

      expect(await screen.findByText("1 of 3")).toBeInTheDocument();
      expect(screen.queryByText(/ready to review/i)).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /intro to testing/i })).not.toBeInTheDocument();
      expect(mockedGetReviewQueue).toHaveBeenNthCalledWith(2, "course-1", 3);
    });

    it("silently supersedes a stale saved session instead of resuming it", async () => {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          courseId: "course-1",
          chosenSize: 5,
          remainingCardIds: ["stale-1", "stale-2"],
          gradedTally: {},
          startedAt: Date.now(),
        }),
      );
      mockSearchParams = new URLSearchParams({ course: "course-1", start: "due" });
      mockedGetReviewQueue
        .mockResolvedValueOnce(ok(makeQueue({ due: 1, total: 1 })))
        .mockResolvedValueOnce(ok(makeQueue({ due: 1, cards: [makeQueueCard({ id: "fresh-1" })] })));

      render(<ReviewPage />);

      expect(await screen.findByText("1 of 1")).toBeInTheDocument();
      expect(screen.queryByText(/resumed session/i)).not.toBeInTheDocument();
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
      expect(stored).toMatchObject({ remainingCardIds: ["fresh-1"] });
    });

    it("falls back to the chooser when nothing is due, showing new cards there instead of starting an empty session", async () => {
      mockSearchParams = new URLSearchParams({ course: "course-1", start: "due" });
      // Two calls, not one: the bootstrap effect's own due-count lookup,
      // then the chooser phase's own effect refetching once phase flips —
      // a small, harmless redundancy in this uncommon fallback path.
      mockedGetReviewQueue.mockResolvedValue(ok(makeQueue({ due: 0, new: 2, total: 2 })));

      render(<ReviewPage />);

      // total > 0 (there are new cards) so the chooser offers them, rather
      // than the "All caught up" empty state which only applies at total===0.
      expect(await screen.findByText(/ready to review/i)).toBeInTheDocument();
      expect(screen.getByText(/0 due · 2 new/i)).toBeInTheDocument();
      expect(mockedGetReviewQueue).toHaveBeenCalledTimes(2);
    });

    it("falls back to the chooser's empty state when there is truly nothing due or new", async () => {
      mockSearchParams = new URLSearchParams({ course: "course-1", start: "due" });
      mockedGetReviewQueue.mockResolvedValue(ok(makeQueue({ due: 0, new: 0, total: 0 })));

      render(<ReviewPage />);

      expect(await screen.findByText("All caught up")).toBeInTheDocument();
    });
  });
});
