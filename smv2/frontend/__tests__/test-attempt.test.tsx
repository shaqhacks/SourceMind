import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import TestAttemptClient from "@/components/test/TestAttemptClient";
import {
  getTest,
  retakeTest,
  submitTest,
  type SubmitTestOut,
  type TestAttemptOut,
} from "@/lib/api/client";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

import { err, ok } from "./support/api-result";

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/course/course-1/test/attempt-1",
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/lib/api/client", () => ({
  getTest: vi.fn(),
  submitTest: vi.fn(),
  retakeTest: vi.fn(),
}));

vi.mock("@/lib/review/reviewBus", () => ({
  notifyReviewSettled: vi.fn(),
}));

const mockedGetTest = vi.mocked(getTest);
const mockedSubmitTest = vi.mocked(submitTest);
const mockedRetakeTest = vi.mocked(retakeTest);
const mockedNotifyReviewSettled = vi.mocked(notifyReviewSettled);

function makeAttempt(overrides: Partial<TestAttemptOut> = {}): TestAttemptOut {
  return {
    id: "attempt-1",
    test_id: "test-1",
    course_id: "course-1",
    chapter_label: null,
    score: null,
    questions: [
      { question: "2+2=?", choices: ["3", "4", "5", "6"], correct_index: null, explanation: null },
      {
        question: "Capital of France?",
        choices: ["Berlin", "Paris", "Rome", "Madrid"],
        correct_index: null,
        explanation: null,
      },
    ],
    answers: null,
    results: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeSubmitResult(overrides: Partial<SubmitTestOut> = {}): SubmitTestOut {
  return {
    score: 0.5,
    added_card_ids: [],
    due_now_count: 0,
    results: [
      { correct: true, correct_index: 1, explanation: "4 is correct because 2+2=4.", your_answer: 1 },
      { correct: false, correct_index: 1, explanation: "Paris is the capital of France.", your_answer: 0 },
    ],
    ...overrides,
  };
}

describe("TestAttemptClient", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("never renders correct_index/explanation before submit — the API redacts them", async () => {
    mockedGetTest.mockResolvedValue(ok(makeAttempt()));

    render(<TestAttemptClient courseId="course-1" attemptId="attempt-1" />);

    await screen.findByText("2+2=?");
    expect(screen.queryByText(/correct/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/incorrect/i)).not.toBeInTheDocument();
    expect(screen.queryByText("4 is correct because 2+2=4.")).not.toBeInTheDocument();
  });

  it("shows a retryable error banner on load failure, and retry recovers", async () => {
    mockedGetTest.mockResolvedValueOnce(err()).mockResolvedValueOnce(ok(makeAttempt()));

    render(<TestAttemptClient courseId="course-1" attemptId="attempt-1" />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/loading quiz/i);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("2+2=?")).toBeInTheDocument();
  });

  it("blocks advancing with an unanswered guard, and keys 1-4 + Enter select/advance/submit", async () => {
    mockedGetTest.mockResolvedValue(ok(makeAttempt()));
    mockedSubmitTest.mockResolvedValue(ok(makeSubmitResult()));

    render(<TestAttemptClient courseId="course-1" attemptId="attempt-1" />);
    await screen.findByText("2+2=?");

    fireEvent.keyDown(window, { key: "Enter" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/select an answer/i);
    expect(screen.getByText("2+2=?")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "2" });
    expect(screen.getByRole("radio", { name: "4" })).toBeChecked();

    fireEvent.keyDown(window, { key: "Enter" });
    expect(await screen.findByText("Capital of France?")).toBeInTheDocument();
    expect(screen.getByText("2 of 2")).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "1" });
    fireEvent.keyDown(window, { key: "Enter" });

    expect(mockedSubmitTest).toHaveBeenCalledWith("attempt-1", [1, 0]);
  });

  it("submitting shows the score and a per-question review with accessible (not color-only) correctness marking", async () => {
    mockedGetTest.mockResolvedValue(ok(makeAttempt()));
    mockedSubmitTest.mockResolvedValue(ok(makeSubmitResult()));

    render(<TestAttemptClient courseId="course-1" attemptId="attempt-1" />);
    await screen.findByText("2+2=?");

    fireEvent.keyDown(window, { key: "2" });
    fireEvent.keyDown(window, { key: "Enter" });
    await screen.findByText("Capital of France?");
    fireEvent.keyDown(window, { key: "1" });
    fireEvent.keyDown(window, { key: "Enter" });

    expect(await screen.findByText(/score: 50%/i)).toBeInTheDocument();
    expect(screen.getByText(/✓ correct/i)).toBeInTheDocument();
    expect(screen.getByText(/✗ incorrect/i)).toBeInTheDocument();
    expect(screen.getByText(/paris is the capital of france/i)).toBeInTheDocument();
    expect(screen.getByText(/your answer: berlin/i)).toBeInTheDocument();
    expect(screen.getByText(/correct answer: paris/i)).toBeInTheDocument();
  });

  it("shows a missed-concepts banner when added_card_ids is non-empty, and fires notifyReviewSettled", async () => {
    mockedGetTest.mockResolvedValue(ok(makeAttempt()));
    mockedSubmitTest.mockResolvedValue(
      ok(makeSubmitResult({ added_card_ids: ["card-1", "card-2"] })),
    );

    render(<TestAttemptClient courseId="course-1" attemptId="attempt-1" />);
    await screen.findByText("2+2=?");

    fireEvent.keyDown(window, { key: "2" });
    fireEvent.keyDown(window, { key: "Enter" });
    await screen.findByText("Capital of France?");
    fireEvent.keyDown(window, { key: "1" });
    fireEvent.keyDown(window, { key: "Enter" });

    // Wait for a piece of text unique to the post-submit view first — the
    // in-progress "N of 2" indicator also has role="status", so querying
    // for the banner by role alone races the async submit and can match
    // that stale element before the real banner ever renders.
    await screen.findByText(/score: 50%/i);
    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent(/2 missed concepts added to your reviews/i);
    expect(mockedNotifyReviewSettled).toHaveBeenCalled();
  });

  it("shows a 'Start review' CTA linking to a due-now session when cards are due, hidden otherwise", async () => {
    mockedGetTest.mockResolvedValue(ok(makeAttempt()));
    mockedSubmitTest.mockResolvedValue(ok(makeSubmitResult({ due_now_count: 5 })));

    render(<TestAttemptClient courseId="course-1" attemptId="attempt-1" />);
    await screen.findByText("2+2=?");
    fireEvent.keyDown(window, { key: "2" });
    fireEvent.keyDown(window, { key: "Enter" });
    await screen.findByText("Capital of France?");
    fireEvent.keyDown(window, { key: "1" });
    fireEvent.keyDown(window, { key: "Enter" });

    const link = await screen.findByRole("link", { name: /start review.*5 cards due now/i });
    expect(link).toHaveAttribute("href", "/review?course=course-1&start=due");
  });

  it("hides the 'Start review' CTA when no cards are due", async () => {
    mockedGetTest.mockResolvedValue(ok(makeAttempt()));
    mockedSubmitTest.mockResolvedValue(ok(makeSubmitResult({ due_now_count: 0 })));

    render(<TestAttemptClient courseId="course-1" attemptId="attempt-1" />);
    await screen.findByText("2+2=?");
    fireEvent.keyDown(window, { key: "2" });
    fireEvent.keyDown(window, { key: "Enter" });
    await screen.findByText("Capital of France?");
    fireEvent.keyDown(window, { key: "1" });
    fireEvent.keyDown(window, { key: "Enter" });

    await screen.findByText(/score: 50%/i);
    expect(screen.queryByRole("link", { name: /start review/i })).not.toBeInTheDocument();
  });

  it("'Retake test' starts a zero-LLM retake and navigates straight into the new attempt", async () => {
    mockedGetTest.mockResolvedValue(ok(makeAttempt()));
    mockedSubmitTest.mockResolvedValue(ok(makeSubmitResult()));
    mockedRetakeTest.mockResolvedValue(ok({ attempt_id: "attempt-2" }));

    render(<TestAttemptClient courseId="course-1" attemptId="attempt-1" />);
    await screen.findByText("2+2=?");
    fireEvent.keyDown(window, { key: "2" });
    fireEvent.keyDown(window, { key: "Enter" });
    await screen.findByText("Capital of France?");
    fireEvent.keyDown(window, { key: "1" });
    fireEvent.keyDown(window, { key: "Enter" });

    await screen.findByText(/score: 50%/i);
    fireEvent.click(screen.getByRole("button", { name: /retake test/i }));

    // Retake targets the persisted Test/deck (test_id), not this specific
    // attempt — retaking attempt-1 again should still work after a course
    // has many attempts against the same test.
    expect(mockedRetakeTest).toHaveBeenCalledWith("test-1");
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/course/course-1/test/attempt-2"));
  });

  it("uses singular 'concept' for exactly one missed card", async () => {
    mockedGetTest.mockResolvedValue(ok(makeAttempt()));
    mockedSubmitTest.mockResolvedValue(ok(makeSubmitResult({ added_card_ids: ["card-1"] })));

    render(<TestAttemptClient courseId="course-1" attemptId="attempt-1" />);
    await screen.findByText("2+2=?");

    fireEvent.keyDown(window, { key: "2" });
    fireEvent.keyDown(window, { key: "Enter" });
    await screen.findByText("Capital of France?");
    fireEvent.keyDown(window, { key: "1" });
    fireEvent.keyDown(window, { key: "Enter" });

    expect(await screen.findByText(/1 missed concept added to your reviews/i)).toBeInTheDocument();
  });

  it("shows no banner when added_card_ids is absent or empty", async () => {
    mockedGetTest.mockResolvedValue(ok(makeAttempt()));
    mockedSubmitTest.mockResolvedValue(ok(makeSubmitResult({ added_card_ids: [] })));

    render(<TestAttemptClient courseId="course-1" attemptId="attempt-1" />);
    await screen.findByText("2+2=?");

    fireEvent.keyDown(window, { key: "2" });
    fireEvent.keyDown(window, { key: "Enter" });
    await screen.findByText("Capital of France?");
    fireEvent.keyDown(window, { key: "1" });
    fireEvent.keyDown(window, { key: "Enter" });

    await screen.findByText(/score: 50%/i);
    expect(screen.queryByText(/missed concept/i)).not.toBeInTheDocument();
    expect(mockedNotifyReviewSettled).toHaveBeenCalled();
  });
});
