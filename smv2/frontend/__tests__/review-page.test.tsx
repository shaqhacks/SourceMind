import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReviewPage from "@/app/review/page";
import {
  getReviewQueue,
  getReviewSelection,
  getAdaptiveStudyQueue,
  getReviewSummary,
  gradeCard,
  submitPracticeAnswer,
  type ReviewQueueCardOut,
  type ReviewQueueOut,
  type ReviewSelectionOut,
  type ReviewSummaryOut,
  type AdaptiveStudyActivityOut,
  type AdaptiveStudyQueueOut,
} from "@/lib/api/client";
import {
  ACTIVE_REVIEW_SESSION_STORAGE_KEY,
  COMPLETED_REVIEW_SESSION_STORAGE_KEY,
  type ActiveReviewSession,
  type CompletedReviewSession,
} from "@/lib/review/sessionStorage";

import { err, ok } from "./support/api-result";

let mockSearchParams = new URLSearchParams();
const mockPush = vi.fn();
const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
  useSearchParams: () => mockSearchParams,
  usePathname: () => "/review",
}));

vi.mock("@/lib/api/client", () => ({
  MAX_QUEUE_FETCH: 200,
  getReviewSummary: vi.fn(),
  getReviewQueue: vi.fn(),
  getReviewSelection: vi.fn(),
  getAdaptiveStudyQueue: vi.fn(),
  gradeCard: vi.fn(),
  submitPracticeAnswer: vi.fn(),
}));

const mockedGetReviewSummary = vi.mocked(getReviewSummary);
const mockedGetReviewQueue = vi.mocked(getReviewQueue);
const mockedGetReviewSelection = vi.mocked(getReviewSelection);
const mockedGetAdaptiveStudyQueue = vi.mocked(getAdaptiveStudyQueue);
const mockedGradeCard = vi.mocked(gradeCard);
const mockedSubmitPracticeAnswer = vi.mocked(submitPracticeAnswer);

function makeSummary(overrides: Partial<ReviewSummaryOut> = {}): ReviewSummaryOut {
  return {
    courses: [
      {
        course_id: "course-1",
        title: "Intro to Testing",
        due_count: 5,
        overdue_count: 5,
        new_count: 2,
        available_count: 7,
        total_count: 7,
        needs_attention_count: 0,
      },
    ],
    due_total: 7,
    daily_throughput: 3,
    backlog_warning: false,
    ...overrides,
  };
}

function makeQueue(overrides: Partial<ReviewQueueOut> = {}): ReviewQueueOut {
  const total = overrides.total ?? 7;
  const due = overrides.due ?? Math.min(5, total);
  const newCount = overrides.new ?? Math.max(total - due, 0);
  return {
    cards: [],
    due,
    new: newCount,
    total,
    overdue_count: due,
    new_count: newCount,
    available_count: due + newCount,
    total_count: total,
    ...overrides,
  };
}

function makeQueueCard(overrides: Partial<ReviewQueueCardOut> = {}): ReviewQueueCardOut {
  return {
    id: "card-1",
    section_id: "sec-1",
    front_md: "What is 2+2?",
    back_md: "4",
    due_at: "2026-01-01T00:00:00Z",
    is_new: false,
    // Default fixture represents a once-reviewed card ("first Good" state,
    // per srs_service's bootstrap table) — is_new:false above wouldn't be
    // internally consistent with the all-new bootstrap values.
    interval_days: 1.0,
    ease: 2.5,
    reps: 1,
    chapter_label: "Chapter 1",
    section_title: "Section 1",
    is_due: true,
    last_grade: null,
    ...overrides,
  };
}

function makeSelection(overrides: Partial<ReviewSelectionOut> = {}): ReviewSelectionOut {
  return {
    cards: [],
    missing_card_ids: [],
    ...overrides,
  };
}

function makeAdaptiveQueue(overrides: Partial<AdaptiveStudyQueueOut> = {}): AdaptiveStudyQueueOut {
  return { activities: [], ...overrides };
}

function makeQuestion(overrides: Partial<AdaptiveStudyActivityOut> = {}): AdaptiveStudyActivityOut {
  return {
    activity_id: "question-1",
    activity_type: "question",
    concept_id: "concept-1",
    learning_claim_id: "claim-1",
    due_at: null,
    readiness_state: "likely_struggling",
    reason: "targeted_remediation",
    payload: {
      stem_md: "Which statement matches the reading?",
      choices: ["The supported statement", "A distractor"],
    },
    ...overrides,
  };
}

function completedSession(overrides: Partial<CompletedReviewSession> = {}): CompletedReviewSession {
  return {
    version: 1,
    sessionId: "session-1",
    courseId: "course-1",
    scope: "all",
    chapterLabel: null,
    endedAt: Date.now(),
    gradedTally: { 1: 2, 2: 0, 3: 1, 4: 0 },
    againCardIds: ["card-3", "card-1"],
    ...overrides,
  };
}

function activeSession(overrides: Partial<ActiveReviewSession> = {}): ActiveReviewSession {
  return {
    version: 1,
    sessionId: "active-session",
    courseId: "course-1",
    scope: "available",
    chapterLabel: null,
    chosenSize: 2,
    remainingCardIds: ["stale-1", "stale-2"],
    gradedTally: {},
    againCardIds: [],
    startedAt: Date.now(),
    ...overrides,
  };
}

function seedCompletedSession(overrides: Partial<CompletedReviewSession> = {}) {
  localStorage.setItem(COMPLETED_REVIEW_SESSION_STORAGE_KEY, JSON.stringify(completedSession(overrides)));
}

function deferredGradeResponse() {
  let resolve!: (value: Awaited<ReturnType<typeof gradeCard>>) => void;
  const promise = new Promise<Awaited<ReturnType<typeof gradeCard>>>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function deferredSelectionResponse() {
  let resolve!: (value: ReturnType<typeof ok<ReviewSelectionOut>>) => void;
  const promise = new Promise<ReturnType<typeof ok<ReviewSelectionOut>>>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

async function completeOneCardSession(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /review all \(1\)/i }));
  expect(await screen.findByText("1 of 1")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /reveal/i }));
  await user.click(screen.getByRole("button", { name: /again/i }));
  expect(await screen.findByText("Session complete")).toBeInTheDocument();
}

describe("ReviewPage", () => {
  beforeEach(() => {
    mockSearchParams = new URLSearchParams();
    mockPush.mockReset();
    mockReplace.mockReset();
    mockedGetReviewSummary.mockReset();
    mockedGetReviewQueue.mockReset();
    mockedGetReviewSelection.mockReset();
    mockedGetAdaptiveStudyQueue.mockReset();
    mockedGradeCard.mockReset();
    mockedSubmitPracticeAnswer.mockReset();
    mockedGradeCard.mockResolvedValue(ok({ next_due_at: "2026-01-02T00:00:00Z", remaining_due: 0 }));
    mockedGetReviewSelection.mockResolvedValue(ok(makeSelection()));
    mockedGetAdaptiveStudyQueue.mockResolvedValue(ok(makeAdaptiveQueue()));
    mockedSubmitPracticeAnswer.mockResolvedValue(ok({
      question_id: "question-1",
      selected_index: 0,
      correct: true,
      correct_index: 0,
      explanation_md: "Because the source says so.",
      concept: { id: "concept-1", slug: "concept-1", label: "Concept 1" },
      readiness_estimate: null,
      evidence_state: "insufficient_evidence",
      evidence_count: 0,
      already_answered: false,
    }));
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
  });

  it("hub: shows the backlog warning and course list from review_summary", async () => {
    mockedGetReviewSummary.mockResolvedValue(
      ok(
        makeSummary({
          backlog_warning: true,
          courses: [
            {
              course_id: "course-1",
              title: "Intro to Testing",
              due_count: 40,
              overdue_count: 40,
              new_count: 2,
              available_count: 42,
              total_count: 42,
              needs_attention_count: 0,
            },
          ],
          due_total: 42,
        }),
      ),
    );

    render(<ReviewPage />);

    expect(await screen.findByText(/40 overdue — more than 2 days at your pace/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /intro to testing/i })).toHaveTextContent(
      /40 overdue · 2 new/i,
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
    mockedGetReviewQueue.mockResolvedValue(
      ok(makeQueue({ due: 0, new: 0, total: 0, overdue_count: 0, new_count: 0, available_count: 0, total_count: 0 })),
    );

    render(<ReviewPage />);

    expect(await screen.findByText("All caught up")).toBeInTheDocument();
  });

  it("chooser: treats future-scheduled cards as caught up instead of starting an empty session", async () => {
    mockSearchParams = new URLSearchParams({ course: "course-1" });
    mockedGetReviewQueue.mockResolvedValue(
      ok(
        makeQueue({
          due: 0,
          new: 0,
          total: 5,
          overdue_count: 0,
          new_count: 0,
          available_count: 0,
          total_count: 5,
        }),
      ),
    );

    render(<ReviewPage />);

    expect(await screen.findByText("All caught up")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /review all/i })).not.toBeInTheDocument();
  });

  it("chooser: chapter-scoped review sizes itself from filtered chapter cards, not course-wide counts", async () => {
    mockSearchParams = new URLSearchParams({ course: "course-1", chapter: "Chapter 1" });
    mockedGetReviewQueue
      .mockResolvedValueOnce(
        ok(
          makeQueue({
            total: 30,
            due: 25,
            new: 5,
            cards: [
              makeQueueCard({ id: "chapter-card-1", chapter_label: "Chapter 1", is_due: true, is_new: false }),
              makeQueueCard({
                id: "chapter-card-2",
                chapter_label: "Chapter 1",
                is_due: false,
                is_new: true,
              }),
            ],
          }),
        ),
      )
      .mockResolvedValueOnce(
        ok(
          makeQueue({
            total: 30,
            due: 25,
            new: 5,
            cards: [
              makeQueueCard({ id: "chapter-card-1", chapter_label: "Chapter 1", is_due: true, is_new: false }),
              makeQueueCard({
                id: "chapter-card-2",
                chapter_label: "Chapter 1",
                is_due: false,
                is_new: true,
              }),
            ],
          }),
        ),
      );
    const user = userEvent.setup();

    render(<ReviewPage />);

    expect(await screen.findByText(/1 due · 1 new/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /review all \(2\)/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^review 10$/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /review all \(2\)/i }));

    expect(await screen.findByText("1 of 2")).toBeInTheDocument();
    expect(mockedGetReviewQueue).toHaveBeenNthCalledWith(2, "course-1", {
      limit: 2,
      scope: undefined,
      chapterLabel: "Chapter 1",
    });
    expect(mockedGetReviewQueue).not.toHaveBeenCalledWith(
      "course-1",
      expect.objectContaining({ limit: 30 }),
    );
  });

  it("chooser: scope=all and scope=needs_attention are passed through to queue lookups", async () => {
    mockSearchParams = new URLSearchParams({ course: "course-1", scope: "needs_attention" });
    mockedGetReviewQueue.mockResolvedValue(ok(makeQueue({ total: 1, due: 1 })));

    render(<ReviewPage />);

    expect(await screen.findByText(/ready to review/i)).toBeInTheDocument();
    expect(mockedGetReviewQueue).toHaveBeenCalledWith("course-1", {
      limit: 200,
      scope: "needs_attention",
      chapterLabel: undefined,
    });

    cleanup();
    vi.clearAllMocks();
    mockedGetAdaptiveStudyQueue.mockResolvedValue(ok(makeAdaptiveQueue()));
    mockedGetReviewQueue.mockResolvedValue(ok(makeQueue({ total: 1, due: 1 })));
    mockSearchParams = new URLSearchParams({ course: "course-1", scope: "all" });

    render(<ReviewPage />);

    expect(await screen.findByText(/ready to review/i)).toBeInTheDocument();
    expect(mockedGetReviewQueue).toHaveBeenCalledWith("course-1", {
      limit: 200,
      scope: "all",
      chapterLabel: undefined,
    });
  });

  it("chooser: explicit query intent supersedes stale active storage", async () => {
    localStorage.setItem(
      ACTIVE_REVIEW_SESSION_STORAGE_KEY,
      JSON.stringify(activeSession({ remainingCardIds: ["stale-1"] })),
    );
    mockSearchParams = new URLSearchParams({ course: "course-1", scope: "all" });
    mockedGetReviewQueue.mockResolvedValue(ok(makeQueue({ total: 1, due: 1 })));

    render(<ReviewPage />);

    expect(await screen.findByText(/ready to review/i)).toBeInTheDocument();
    expect(screen.queryByText(/resumed session/i)).not.toBeInTheDocument();
    expect(mockedGetReviewQueue).toHaveBeenCalledWith("course-1", {
      limit: 200,
      scope: "all",
      chapterLabel: undefined,
    });
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
    expect(screen.queryByRole("button", { name: /again/i })).not.toBeInTheDocument();

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
    await user.click(screen.getByRole("button", { name: /easy/i }));

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

  it("returns from completion to the course chooser without relying on remount", async () => {
    mockSearchParams = new URLSearchParams({ course: "course-1", scope: "all" });
    mockedGetReviewQueue
      .mockResolvedValueOnce(ok(makeQueue({ total: 1, due: 1 })))
      .mockResolvedValueOnce(
        ok(makeQueue({ total: 1, cards: [makeQueueCard({ id: "card-1", front_md: "Q1", back_md: "A1" })] })),
      )
      .mockResolvedValueOnce(ok(makeQueue({ total: 1, due: 1 })));
    const user = userEvent.setup();

    render(<ReviewPage />);

    await completeOneCardSession(user);
    await user.click(screen.getByRole("button", { name: "Back to review" }));

    expect(screen.getByRole("heading", { name: "Ready to review" })).toBeVisible();
    expect(mockReplace).toHaveBeenCalledWith("/review?course=course-1");
    expect(localStorage.getItem(COMPLETED_REVIEW_SESSION_STORAGE_KEY)).not.toBeNull();
  });

  it("stores completed snapshots with exact scope, chapter label, tally, and Again IDs", async () => {
    mockSearchParams = new URLSearchParams({
      course: "course-1",
      scope: "needs_attention",
      chapter: "Chapter 7",
    });
    mockedGetReviewQueue
      .mockResolvedValueOnce(
        ok(
          makeQueue({
            total: 1,
            due: 1,
            cards: [
              makeQueueCard({
                id: "card-1",
                front_md: "Q1",
                back_md: "A1",
                chapter_label: "Chapter 7",
              }),
            ],
          }),
        ),
      )
      .mockResolvedValueOnce(
        ok(
          makeQueue({
            total: 1,
            cards: [
              makeQueueCard({
                id: "card-1",
                front_md: "Q1",
                back_md: "A1",
                chapter_label: "Chapter 7",
              }),
            ],
          }),
        ),
      );
    const user = userEvent.setup();

    render(<ReviewPage />);

    await completeOneCardSession(user);

    const raw = localStorage.getItem(COMPLETED_REVIEW_SESSION_STORAGE_KEY);
    expect(raw).not.toBeNull();
    expect(raw).not.toContain("Q1");
    expect(raw).not.toContain("A1");
    expect(JSON.parse(raw ?? "null")).toMatchObject({
      courseId: "course-1",
      scope: "needs_attention",
      chapterLabel: "Chapter 7",
      gradedTally: { 1: 1 },
      againCardIds: ["card-1"],
    });
  });

  it("refreshes completed sessions and follows browser back-forward query changes without remounting", async () => {
    seedCompletedSession({ againCardIds: ["card-3", "card-1"] });
    mockSearchParams = new URLSearchParams({ course: "course-1", completed: "session-1" });
    mockedGetReviewQueue.mockResolvedValue(ok(makeQueue({ total: 1, due: 1 })));
    const { rerender } = render(<ReviewPage />);

    expect(await screen.findByText("Session complete")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review missed (2)" })).toBeInTheDocument();

    mockSearchParams = new URLSearchParams({ course: "course-1" });
    rerender(<ReviewPage />);

    expect(await screen.findByRole("heading", { name: "Ready to review" })).toBeInTheDocument();
    await waitFor(() =>
      expect(mockedGetReviewQueue).toHaveBeenCalledWith("course-1", {
        limit: 200,
        scope: undefined,
        chapterLabel: undefined,
      }),
    );

    mockSearchParams = new URLSearchParams({ course: "course-1", completed: "session-1" });
    rerender(<ReviewPage />);

    expect(await screen.findByText("Session complete")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review missed (2)" })).toBeInTheDocument();
  });

  it("replays the exact Again cards from the completed session", async () => {
    seedCompletedSession({ againCardIds: ["card-3", "card-1"] });
    mockSearchParams = new URLSearchParams({ course: "course-1", completed: "session-1" });
    mockedGetReviewSelection.mockResolvedValue(
      ok(
        makeSelection({
          cards: [
            makeQueueCard({ id: "card-3", front_md: "Q3", back_md: "A3" }),
            makeQueueCard({ id: "card-1", front_md: "Q1", back_md: "A1" }),
          ],
        }),
      ),
    );

    render(<ReviewPage />);

    await userEvent.setup().click(await screen.findByRole("button", { name: "Review missed (2)" }));

    expect(mockedGetReviewSelection).toHaveBeenCalledWith("course-1", ["card-3", "card-1"]);
    expect(await screen.findByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByText("Q3")).toBeInTheDocument();
  });

  it("moves replay sessions off the completed URL and preserves them across refresh", async () => {
    seedCompletedSession({ againCardIds: ["card-3", "card-1"], scope: "needs_attention" });
    mockSearchParams = new URLSearchParams({ course: "course-1", completed: "session-1" });
    mockedGetReviewSelection.mockResolvedValue(
      ok(
        makeSelection({
          cards: [
            makeQueueCard({ id: "card-3", front_md: "Q3", back_md: "A3" }),
            makeQueueCard({ id: "card-1", front_md: "Q1", back_md: "A1" }),
          ],
        }),
      ),
    );
    const user = userEvent.setup();

    const { unmount } = render(<ReviewPage />);
    await user.click(await screen.findByRole("button", { name: "Review missed (2)" }));

    expect(await screen.findByText("1 of 2")).toBeInTheDocument();
    expect(mockReplace).toHaveBeenCalledWith("/review?course=course-1&scope=needs_attention");

    mockSearchParams = new URLSearchParams({ course: "course-1", scope: "needs_attention" });
    unmount();
    mockedGetReviewQueue.mockResolvedValueOnce(
      ok(
        makeQueue({
          total: 2,
          cards: [
            makeQueueCard({ id: "card-3", front_md: "Q3", back_md: "A3" }),
            makeQueueCard({ id: "card-1", front_md: "Q1", back_md: "A1" }),
          ],
        }),
      ),
    );

    render(<ReviewPage />);

    expect(await screen.findByText(/resumed session — 2 left/i)).toBeInTheDocument();
    expect(await screen.findByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByText("Q3")).toBeInTheDocument();
  });

  it("returns browser back-forward from an active replay to completed state without applying stale active state", async () => {
    seedCompletedSession({ againCardIds: ["card-3", "card-1"] });
    mockSearchParams = new URLSearchParams({ course: "course-1", completed: "session-1" });
    mockedGetReviewSelection.mockResolvedValue(
      ok(
        makeSelection({
          cards: [
            makeQueueCard({ id: "card-3", front_md: "Q3", back_md: "A3" }),
            makeQueueCard({ id: "card-1", front_md: "Q1", back_md: "A1" }),
          ],
        }),
      ),
    );
    const user = userEvent.setup();
    const { rerender } = render(<ReviewPage />);

    await user.click(await screen.findByRole("button", { name: "Review missed (2)" }));
    expect(await screen.findByText("1 of 2")).toBeInTheDocument();

    mockedGetReviewQueue.mockResolvedValueOnce(
      ok(
        makeQueue({
          total: 2,
          cards: [
            makeQueueCard({ id: "card-3", front_md: "Q3", back_md: "A3" }),
            makeQueueCard({ id: "card-1", front_md: "Q1", back_md: "A1" }),
          ],
        }),
      ),
    );
    mockSearchParams = new URLSearchParams({ course: "course-1" });
    rerender(<ReviewPage />);

    mockSearchParams = new URLSearchParams({ course: "course-1", completed: "session-1" });
    rerender(<ReviewPage />);

    expect(await screen.findByText("Session complete")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Review missed (2)" })).toBeInTheDocument();
    expect(screen.queryByText("1 of 2")).not.toBeInTheDocument();
  });

  it("ignores a stale replay selection response after the completed session changes", async () => {
    const pendingReplay = deferredSelectionResponse();
    seedCompletedSession({ againCardIds: ["card-3"] });
    mockSearchParams = new URLSearchParams({ course: "course-1", completed: "session-1" });
    mockedGetReviewSelection.mockReturnValueOnce(pendingReplay.promise);
    const user = userEvent.setup();
    const { rerender } = render(<ReviewPage />);

    await user.click(await screen.findByRole("button", { name: "Review missed (1)" }));
    expect(await screen.findByRole("status")).toBeInTheDocument();

    seedCompletedSession({
      sessionId: "session-2",
      gradedTally: { 1: 0, 4: 1 },
      againCardIds: [],
    });
    mockSearchParams = new URLSearchParams({ course: "course-1", completed: "session-2" });
    rerender(<ReviewPage />);

    expect(await screen.findByText("Session complete")).toBeInTheDocument();
    expect(screen.getByText(/easy: 1/i)).toBeInTheDocument();
    await act(async () => {
      pendingReplay.resolve(
        ok(
          makeSelection({
            cards: [makeQueueCard({ id: "card-3", front_md: "Q3", back_md: "A3" })],
          }),
        ),
      );
    });
    expect(screen.queryByText("Q3")).not.toBeInTheDocument();
    expect(screen.getByText("Session complete")).toBeInTheDocument();
    expect(screen.getByText(/easy: 1/i)).toBeInTheDocument();
  });

  it("ignores a stale replay selection response after the active replay query changes", async () => {
    const pendingReplay = deferredSelectionResponse();
    seedCompletedSession({
      againCardIds: ["card-3"],
      scope: "needs_attention",
      chapterLabel: "Chapter 1",
    });
    mockSearchParams = new URLSearchParams({ course: "course-1", completed: "session-1" });
    mockedGetReviewSelection.mockReturnValueOnce(pendingReplay.promise);
    mockedGetReviewQueue.mockResolvedValue(
      ok(makeQueue({ total: 1, due: 1, cards: [makeQueueCard({ id: "other-card", front_md: "Other Q" })] })),
    );
    const user = userEvent.setup();
    const { rerender } = render(<ReviewPage />);

    await user.click(await screen.findByRole("button", { name: "Review missed (1)" }));
    expect(mockReplace).toHaveBeenCalledWith(
      "/review?course=course-1&scope=needs_attention&chapter=Chapter+1",
    );

    mockSearchParams = new URLSearchParams({
      course: "course-1",
      scope: "all",
      chapter: "Chapter 2",
    });
    rerender(<ReviewPage />);
    expect(await screen.findByRole("heading", { name: "Ready to review" })).toBeInTheDocument();

    await act(async () => {
      pendingReplay.resolve(
        ok(
          makeSelection({
            cards: [makeQueueCard({ id: "card-3", front_md: "Q3", back_md: "A3" })],
          }),
        ),
      );
      await Promise.resolve();
    });

    expect(screen.queryByText("Q3")).not.toBeInTheDocument();
    expect(localStorage.getItem(ACTIVE_REVIEW_SESSION_STORAGE_KEY)).toBeNull();
    expect(screen.getByRole("heading", { name: "Ready to review" })).toBeInTheDocument();
  });

  it("reports missing replay cards once while continuing with the returned cards", async () => {
    seedCompletedSession({ againCardIds: ["card-3", "deleted-card", "card-1"] });
    mockSearchParams = new URLSearchParams({ course: "course-1", completed: "session-1" });
    mockedGetReviewSelection.mockResolvedValue(
      ok(
        makeSelection({
          cards: [
            makeQueueCard({ id: "card-3", front_md: "Q3", back_md: "A3" }),
            makeQueueCard({ id: "card-1", front_md: "Q1", back_md: "A1" }),
          ],
          missing_card_ids: ["deleted-card"],
        }),
      ),
    );
    const user = userEvent.setup();

    render(<ReviewPage />);

    await user.click(await screen.findByRole("button", { name: "Review missed (3)" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/1 missed card is no longer available/i);
    expect(await screen.findByText("1 of 2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /reveal/i }));
    await user.click(screen.getByRole("button", { name: /good/i }));
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(await screen.findByText("2 of 2")).toBeInTheDocument();
  });

  it("reports all missing replay cards in the empty replay state", async () => {
    seedCompletedSession({ againCardIds: ["deleted-1", "deleted-2"] });
    mockSearchParams = new URLSearchParams({ course: "course-1", completed: "session-1" });
    mockedGetReviewSelection.mockResolvedValue(
      ok(makeSelection({ cards: [], missing_card_ids: ["deleted-1", "deleted-2"] })),
    );

    render(<ReviewPage />);

    await userEvent.setup().click(await screen.findByRole("button", { name: "Review missed (2)" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/2 missed cards are no longer available/i);
    expect(screen.getByText("All caught up")).toBeInTheDocument();
  });

  it("a new completion replaces the prior completed snapshot under the single storage key", async () => {
    seedCompletedSession({
      sessionId: "old-session",
      gradedTally: { 1: 4 },
      againCardIds: ["old-card"],
    });
    mockSearchParams = new URLSearchParams({ course: "course-1" });
    mockedGetReviewQueue
      .mockResolvedValueOnce(ok(makeQueue({ total: 1, due: 1 })))
      .mockResolvedValueOnce(
        ok(makeQueue({ total: 1, cards: [makeQueueCard({ id: "new-card", front_md: "New Q", back_md: "New A" })] })),
      );
    const user = userEvent.setup();

    render(<ReviewPage />);

    await user.click(await screen.findByRole("button", { name: /review all \(1\)/i }));
    expect(await screen.findByText("1 of 1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /reveal/i }));
    await user.click(screen.getByRole("button", { name: /good/i }));

    const stored = JSON.parse(localStorage.getItem(COMPLETED_REVIEW_SESSION_STORAGE_KEY) ?? "null");
    expect(stored).toMatchObject({
      courseId: "course-1",
      gradedTally: { 3: 1 },
      againCardIds: [],
    });
    expect(stored.sessionId).not.toBe("old-session");
    expect(JSON.stringify(stored)).not.toContain("old-card");
  });

  it("session: failed grade keeps the same card active without advancing tally or storage, then retry succeeds once", async () => {
    const STORAGE_KEY = "smv2.review.session";
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
    mockedGradeCard
      .mockResolvedValueOnce(err(503))
      .mockResolvedValueOnce(ok({ next_due_at: "2026-01-02T00:00:00Z", remaining_due: 1 }));
    const user = userEvent.setup();

    render(<ReviewPage />);

    await user.click(await screen.findByRole("button", { name: /review all \(2\)/i }));
    expect(await screen.findByText("1 of 2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /reveal/i }));
    await user.click(screen.getByRole("button", { name: /good/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/could not save this grade/i);
    expect(screen.getByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByText("Q1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /good/i })).toBeEnabled();
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null")).toMatchObject({
      remainingCardIds: ["card-1", "card-2"],
      gradedTally: {},
    });

    await user.click(screen.getByRole("button", { name: /good/i }));

    expect(mockedGradeCard).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("2 of 2")).toBeInTheDocument();
    expect(screen.getByText("Q2")).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null")).toMatchObject({
      remainingCardIds: ["card-2"],
      gradedTally: { 3: 1 },
    });
  });

  it("session: ignores grade keyboard shortcuts while a grade request is pending", async () => {
    const pendingGrade = deferredGradeResponse();
    mockSearchParams = new URLSearchParams({ course: "course-1" });
    mockedGetReviewQueue
      .mockResolvedValueOnce(ok(makeQueue({ total: 1, due: 1 })))
      .mockResolvedValueOnce(
        ok(makeQueue({ total: 1, cards: [makeQueueCard({ id: "card-1", front_md: "Q1", back_md: "A1" })] })),
      );
    mockedGradeCard.mockReturnValueOnce(pendingGrade.promise);

    render(<ReviewPage />);

    await userEvent.setup().click(await screen.findByRole("button", { name: /review all \(1\)/i }));
    expect(await screen.findByText("1 of 1")).toBeInTheDocument();
    fireEvent.keyDown(window, { key: " " });
    expect(await screen.findByText("A1")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "3" });
    fireEvent.keyDown(window, { key: "4" });

    expect(mockedGradeCard).toHaveBeenCalledTimes(1);
    expect(screen.getByText("1 of 1")).toBeInTheDocument();

    pendingGrade.resolve(ok({ next_due_at: "2026-01-02T00:00:00Z", remaining_due: 0 }));
    expect(await screen.findByText("Session complete")).toBeInTheDocument();
  });

  it("session: includes concept questions, records the answer, and keeps answers out of the queue payload", async () => {
    mockSearchParams = new URLSearchParams({ course: "course-1" });
    mockedGetReviewQueue.mockResolvedValue(ok(makeQueue({ total: 0, due: 0, new: 0 })));
    mockedGetAdaptiveStudyQueue.mockResolvedValue(ok(makeAdaptiveQueue({ activities: [makeQuestion()] })));
    const user = userEvent.setup();

    render(<ReviewPage />);

    await user.click(await screen.findByRole("button", { name: /review all \(1\)/i }));
    expect(await screen.findByText("Which statement matches the reading?")).toBeInTheDocument();
    expect(screen.queryByText(/because the source says so/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "The supported statement" }));

    expect(mockedSubmitPracticeAnswer).toHaveBeenCalledWith("course-1", "question-1", 0);
    expect(await screen.findByText(/because the source says so/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Finish" }));
    expect(await screen.findByText("Session complete")).toBeInTheDocument();
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

      await screen.findByText("2 of 3");
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
        JSON.stringify(activeSession({
          sessionId: "resume-session",
          chosenSize: 5,
          remainingCardIds: ["card-3", "card-4", "card-5"],
          gradedTally: { 3: 1, 2: 1 },
        })),
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
      expect(mockedGetReviewQueue).toHaveBeenNthCalledWith(2, "course-1", { limit: 3 });
    });

    it("silently supersedes a stale saved session instead of resuming it", async () => {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(activeSession({
          sessionId: "stale-session",
          chosenSize: 5,
          remainingCardIds: ["stale-1", "stale-2"],
          gradedTally: {},
        })),
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
      mockedGetReviewQueue.mockResolvedValue(
        ok(makeQueue({ due: 0, new: 2, total: 2, overdue_count: 0, new_count: 2, available_count: 2, total_count: 2 })),
      );

      render(<ReviewPage />);

      // total > 0 (there are new cards) so the chooser offers them, rather
      // than the "All caught up" empty state which only applies at total===0.
      expect(await screen.findByText(/ready to review/i)).toBeInTheDocument();
      expect(screen.getByText(/0 due · 2 new/i)).toBeInTheDocument();
      expect(mockedGetReviewQueue).toHaveBeenCalledTimes(2);
    });

    it("falls back to the chooser's empty state when there is truly nothing due or new", async () => {
      mockSearchParams = new URLSearchParams({ course: "course-1", start: "due" });
      mockedGetReviewQueue.mockResolvedValue(
        ok(makeQueue({ due: 0, new: 0, total: 0, overdue_count: 0, new_count: 0, available_count: 0, total_count: 0 })),
      );

      render(<ReviewPage />);

      expect(await screen.findByText("All caught up")).toBeInTheDocument();
    });

    it("falls back to caught up when only future-scheduled cards exist", async () => {
      mockSearchParams = new URLSearchParams({ course: "course-1", start: "due" });
      mockedGetReviewQueue.mockResolvedValue(
        ok(
          makeQueue({
            due: 0,
            new: 0,
            total: 5,
            overdue_count: 0,
            new_count: 0,
            available_count: 0,
            total_count: 5,
          }),
        ),
      );

      render(<ReviewPage />);

      expect(await screen.findByText("All caught up")).toBeInTheDocument();
      expect(mockedGetReviewQueue).not.toHaveBeenCalledWith("course-1", { limit: 5 });
    });
  });
});
