import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import InlinePracticeAssessment from "@/components/chapter/InlinePracticeAssessment";
import {
  getPracticeAssessment,
  startPracticeAssessment,
  submitPracticeAnswer,
  type PracticeAnsweredOut,
  type PracticeAssessmentOut,
  type PracticeQuestionOut,
  type SubmitPracticeAnswerOut,
} from "@/lib/api/client";

import { err, ok } from "./support/api-result";

vi.mock("@/lib/api/client", () => ({
  getPracticeAssessment: vi.fn(),
  startPracticeAssessment: vi.fn(),
  submitPracticeAnswer: vi.fn(),
}));

const mockedGetPracticeAssessment = vi.mocked(getPracticeAssessment);
const mockedStartPracticeAssessment = vi.mocked(startPracticeAssessment);
const mockedSubmitPracticeAnswer = vi.mocked(submitPracticeAnswer);

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function makeAnswered(overrides: Partial<PracticeAnsweredOut> = {}): PracticeAnsweredOut {
  return {
    answered_at: "2026-01-01T00:00:00Z",
    correct: false,
    correct_index: 1,
    explanation_md: "Use the textbook relationship $F = ma$.",
    mastery_points: 4,
    points_delta: -1,
    selected_index: 0,
    ...overrides,
  };
}

function makeSubmitAnswer(
  overrides: Partial<SubmitPracticeAnswerOut> = {},
): SubmitPracticeAnswerOut {
  return {
    already_answered: false,
    concept: { id: "concept-1", label: "Newton's second law", slug: "newtons-second-law" },
    correct: false,
    correct_index: 1,
    explanation_md: "Use the textbook relationship $F = ma$.",
    mastery_points: 4,
    points_delta: -1,
    question_id: "question-1",
    selected_index: 0,
    ...overrides,
  };
}

function makeQuestion(overrides: Partial<PracticeQuestionOut> = {}): PracticeQuestionOut {
  return {
    id: "question-1",
    problem_number: "1",
    source_ref: "p. 12",
    concept: { id: "concept-1", label: "Newton's second law", slug: "newtons-second-law" },
    stem_md: "What is the net force when $m = 2$ and $a = 3$?",
    choices: ["4 N", "6 N", "8 N"],
    answered: null,
    ...overrides,
  };
}

function makeAssessment(overrides: Partial<PracticeAssessmentOut> = {}): PracticeAssessmentOut {
  return {
    section_id: "section-1",
    status: "ready",
    questions: [makeQuestion()],
    job_id: null,
    message: null,
    run_id: "run-1",
    ...overrides,
  };
}

describe("InlinePracticeAssessment", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("renders ready questions and reveals the textbook answer after a wrong choice", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(ok(makeAssessment()));
    mockedSubmitPracticeAnswer.mockResolvedValue(ok(makeSubmitAnswer()));

    const user = userEvent.setup();
    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    expect(await screen.findByText("Newton's second law")).toBeInTheDocument();
    expect(screen.getByText("p. 12")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "4 N" }));

    expect(mockedSubmitPracticeAnswer).toHaveBeenCalledWith("course-1", "question-1", 0);
    expect(await screen.findByText("Incorrect")).toBeInTheDocument();
    expect(screen.getByText("Concept points 4")).toBeInTheDocument();
    expect(screen.getByText(/textbook relationship/)).toBeInTheDocument();
  });

  it("renders choice content through safe inline Markdown inside accessible buttons", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(
      ok(
        makeAssessment({
          questions: [
            makeQuestion({
              choices: [
                "[linked](https://example.com)",
                "| A | B |\n| - | - |\n| `one` | two |",
                "```ts\nconst unsafe = true;\n```",
              ],
            }),
          ],
        }),
      ),
    );

    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    await screen.findByText("Newton's second law");

    const choiceButtons = screen.getAllByRole("button", { name: /linked|one|unsafe/i });
    for (const button of choiceButtons) {
      expect(button.querySelector("a, table, thead, tbody, tr, th, td, pre, h1, h2, h3")).toBeNull();
    }
    expect(choiceButtons[0]).toHaveAccessibleName("linked");
    expect(choiceButtons[1]).toHaveAccessibleName(/one.*two/i);
    expect(choiceButtons[1].querySelector("code")).not.toBeNull();
    expect(choiceButtons[2]).toHaveAccessibleName(/const unsafe = true/i);
  });

  it("renders LaTeX choice content without raw text fallback", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(
      ok(makeAssessment({ questions: [makeQuestion({ choices: ["$x^2$"] })] })),
    );

    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    await screen.findByText("Newton's second law");

    const mathChoice = screen.getAllByRole("button")[0];
    expect(mathChoice).not.toHaveTextContent("$x^2$");
    expect(mathChoice.querySelector(".katex")).not.toBeNull();
  });

  it("shows a generating state while extraction is pending", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(
      ok(makeAssessment({ status: "generating", questions: undefined })),
    );

    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    expect(await screen.findByRole("status")).toHaveTextContent(/preparing practice questions/i);
  });

  it("continues polling while extraction remains generating until questions are ready", async () => {
    vi.useFakeTimers();
    mockedGetPracticeAssessment
      .mockResolvedValueOnce(ok(makeAssessment({ status: "generating", questions: undefined })))
      .mockResolvedValueOnce(ok(makeAssessment({ status: "generating", questions: undefined })))
      .mockResolvedValueOnce(ok(makeAssessment()));

    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByRole("status")).toHaveTextContent(/preparing practice questions/i);
    expect(mockedGetPracticeAssessment).toHaveBeenCalledTimes(1);

    await act(async () => {
      vi.advanceTimersByTime(1500);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(mockedGetPracticeAssessment).toHaveBeenCalledTimes(2);
    expect(screen.getByRole("status")).toHaveTextContent(/preparing practice questions/i);

    await act(async () => {
      vi.advanceTimersByTime(1500);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText("Newton's second law")).toBeInTheDocument();
    expect(mockedGetPracticeAssessment).toHaveBeenCalledTimes(3);
  });

  it("starts extraction with POST when read-only status is not_started", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(
      ok(makeAssessment({ status: "not_started", questions: undefined })),
    );
    mockedStartPracticeAssessment.mockResolvedValue(
      ok(makeAssessment({ status: "generating", questions: undefined })),
    );

    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    await waitFor(() =>
      expect(mockedStartPracticeAssessment).toHaveBeenCalledWith("course-1", "section-1"),
    );
    expect(mockedStartPracticeAssessment).toHaveBeenCalledTimes(1);
  });

  it("ignores a stale not_started start after props change", async () => {
    const oldStart = deferred<Awaited<ReturnType<typeof startPracticeAssessment>>>();
    mockedGetPracticeAssessment
      .mockResolvedValueOnce(ok(makeAssessment({ status: "not_started", questions: undefined })))
      .mockResolvedValueOnce(ok(makeAssessment({ section_id: "section-2" })));
    mockedStartPracticeAssessment.mockReturnValueOnce(oldStart.promise);

    const { rerender } = render(
      <InlinePracticeAssessment courseId="course-1" sectionId="section-1" />,
    );

    await waitFor(() =>
      expect(mockedStartPracticeAssessment).toHaveBeenCalledWith("course-1", "section-1"),
    );

    rerender(<InlinePracticeAssessment courseId="course-1" sectionId="section-2" />);
    expect(await screen.findByText("Newton's second law")).toBeInTheDocument();

    oldStart.resolve(ok(makeAssessment({ status: "generating", questions: undefined })));
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText("Newton's second law")).toBeInTheDocument();
    expect(screen.queryByText(/preparing practice questions/i)).not.toBeInTheDocument();
  });

  it("does not update state after unmount during start", async () => {
    const oldStart = deferred<Awaited<ReturnType<typeof startPracticeAssessment>>>();
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    mockedGetPracticeAssessment.mockResolvedValue(
      ok(makeAssessment({ status: "not_started", questions: undefined })),
    );
    mockedStartPracticeAssessment.mockReturnValue(oldStart.promise);

    const { unmount } = render(
      <InlinePracticeAssessment courseId="course-1" sectionId="section-1" />,
    );

    await waitFor(() => expect(mockedStartPracticeAssessment).toHaveBeenCalledTimes(1));
    unmount();

    oldStart.resolve(ok(makeAssessment({ status: "generating", questions: undefined })));
    await act(async () => {
      await Promise.resolve();
    });

    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });

  it("shows failed extraction through ErrorBanner and retries", async () => {
    mockedGetPracticeAssessment
      .mockResolvedValueOnce(
        ok(
          makeAssessment({
            status: "failed",
            questions: undefined,
            message: "Extraction failed for this section.",
          }),
        ),
      )
      .mockResolvedValueOnce(ok(makeAssessment()));

    const user = userEvent.setup();
    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Extraction failed for this section.",
    );

    await user.click(screen.getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("Newton's second law")).toBeInTheDocument();
    expect(mockedGetPracticeAssessment).toHaveBeenCalledTimes(2);
  });

  it("renders answered summaries as locked without resubmitting", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(
      ok(
        makeAssessment({
          questions: [makeQuestion({ answered: makeAnswered({ correct: true }) })],
        }),
      ),
    );

    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    expect(await screen.findByText("Correct")).toBeInTheDocument();
    expect(screen.getByText("Concept points 4")).toBeInTheDocument();
    expect(screen.getByText(/textbook relationship/)).toBeInTheDocument();
    for (const button of screen.getAllByRole("button", { name: /^[468] N$/ })) {
      expect(button).toBeDisabled();
    }
    expect(mockedSubmitPracticeAnswer).not.toHaveBeenCalled();
  });

  it("shows a retryable error when load fails", async () => {
    mockedGetPracticeAssessment
      .mockResolvedValueOnce(err())
      .mockResolvedValueOnce(ok(makeAssessment()));

    const user = userEvent.setup();
    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/practice questions/i);

    await user.click(screen.getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("Newton's second law")).toBeInTheDocument();
    expect(mockedGetPracticeAssessment).toHaveBeenCalledTimes(2);
  });

  it("shows submit error without locking question", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(ok(makeAssessment()));
    mockedSubmitPracticeAnswer.mockResolvedValue(err());

    const user = userEvent.setup();
    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    const choice = await screen.findByRole("button", { name: "4 N" });
    await user.click(choice);

    expect(await screen.findByText(/could not submit answer/i)).toBeInTheDocument();
    expect(choice).not.toBeDisabled();
  });
});
