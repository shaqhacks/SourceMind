import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import TestAttemptClient from "@/components/test/TestAttemptClient";
import {
  getTest,
  submitTest,
  type SubmitTestOut,
  type TestAttemptOut,
} from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({
  getTest: vi.fn(),
  submitTest: vi.fn(),
}));

const mockedGetTest = vi.mocked(getTest);
const mockedSubmitTest = vi.mocked(submitTest);

function makeAttempt(overrides: Partial<TestAttemptOut> = {}): TestAttemptOut {
  return {
    id: "attempt-1",
    course_id: "course-1",
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
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeSubmitResult(overrides: Partial<SubmitTestOut> = {}): SubmitTestOut {
  return {
    score: 0.5,
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
    mockedGetTest.mockResolvedValue({ status: 200, ok: true, data: makeAttempt() });

    render(<TestAttemptClient courseId="course-1" attemptId="attempt-1" />);

    await screen.findByText("2+2=?");
    expect(screen.queryByText(/correct/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/incorrect/i)).not.toBeInTheDocument();
    expect(screen.queryByText("4 is correct because 2+2=4.")).not.toBeInTheDocument();
  });

  it("shows a retryable error banner on load failure, and retry recovers", async () => {
    mockedGetTest
      .mockResolvedValueOnce({ status: undefined, ok: false })
      .mockResolvedValueOnce({ status: 200, ok: true, data: makeAttempt() });

    render(<TestAttemptClient courseId="course-1" attemptId="attempt-1" />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/loading quiz/i);
    fireEvent.click(screen.getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("2+2=?")).toBeInTheDocument();
  });

  it("blocks advancing with an unanswered guard, and keys 1-4 + Enter select/advance/submit", async () => {
    mockedGetTest.mockResolvedValue({ status: 200, ok: true, data: makeAttempt() });
    mockedSubmitTest.mockResolvedValue({ status: 200, ok: true, data: makeSubmitResult() });

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
    mockedGetTest.mockResolvedValue({ status: 200, ok: true, data: makeAttempt() });
    mockedSubmitTest.mockResolvedValue({ status: 200, ok: true, data: makeSubmitResult() });

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
});
