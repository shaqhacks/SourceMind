import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import InlinePracticeAssessment from "@/components/chapter/InlinePracticeAssessment";
import type { PracticeSectionState } from "@/components/chapter/practiceAssessmentState";
import {
  type ApiErrorDetail,
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

const readinessDetail: ApiErrorDetail = {
  code: "llm_readiness_unavailable",
  failure_category: "ollama_model_unavailable",
  message: "Your configured Ollama model is not present.",
  remediation: "Open Settings and select a currently installed model.",
};

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
    evidence_count: 0,
    evidence_state: "insufficient_evidence",
    readiness_estimate: null,
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
    evidence_count: 0,
    evidence_state: "insufficient_evidence",
    readiness_estimate: null,
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

function practiceChild({
  onStateChange,
  retryVersion = 0,
  sectionId = "section-1",
}: {
  onStateChange?: (state: PracticeSectionState) => void;
  retryVersion?: number;
  sectionId?: string;
}) {
  return (
    <InlinePracticeAssessment
      courseId="course-1"
      sectionId={sectionId}
      retryVersion={retryVersion}
      onStateChange={onStateChange}
    />
  );
}

function renderPracticeChild(options: Parameters<typeof practiceChild>[0] = {}) {
  return render(practiceChild(options));
}

function CallbackIdentityWrapper({
  onStateChange,
}: {
  onStateChange: (state: PracticeSectionState) => void;
}) {
  const [rerenderCount, setRerenderCount] = useState(0);

  return (
    <>
      <button type="button" onClick={() => setRerenderCount((count) => count + 1)}>
        Rerender parent {rerenderCount}
      </button>
      <InlinePracticeAssessment
        courseId="course-1"
        sectionId="section-1"
        retryVersion={0}
        onStateChange={(state) => onStateChange(state)}
      />
    </>
  );
}

async function flushPracticeTasks() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function advancePracticePoll() {
  await act(async () => {
    vi.advanceTimersByTime(1500);
    await Promise.resolve();
    await Promise.resolve();
  });
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
    expect(screen.getByText("Readiness needs more evidence")).toBeInTheDocument();
    expect(screen.getByText("0 evidence items")).toBeInTheDocument();
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

  it("reports generating and ready transitions to its parent", async () => {
    vi.useFakeTimers();
    const onStateChange = vi.fn();
    mockedGetPracticeAssessment
      .mockResolvedValueOnce(ok(makeAssessment({ status: "generating", questions: [] })))
      .mockResolvedValueOnce(ok(makeAssessment({ status: "ready", questions: [makeQuestion()] })));

    renderPracticeChild({ retryVersion: 0, onStateChange });

    await flushPracticeTasks();
    await advancePracticePoll();

    expect(onStateChange).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "generating", sectionId: "section-1" }),
    );
    expect(onStateChange).toHaveBeenCalledWith(
      expect.objectContaining({ kind: "ready", sectionId: "section-1", questionCount: 1 }),
    );
  });

  it("does not restart loading when a parent rerender changes onStateChange identity", async () => {
    const onStateChange = vi.fn();
    mockedGetPracticeAssessment.mockResolvedValue(ok(makeAssessment()));

    const user = userEvent.setup();
    render(<CallbackIdentityWrapper onStateChange={onStateChange} />);

    expect(await screen.findByText("Newton's second law")).toBeInTheDocument();
    expect(mockedGetPracticeAssessment).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: /rerender parent/i }));
    await flushPracticeTasks();

    expect(mockedGetPracticeAssessment).toHaveBeenCalledTimes(1);
    expect(mockedStartPracticeAssessment).not.toHaveBeenCalled();
  });

  it("does not notify the parent again for repeated generating poll payloads", async () => {
    vi.useFakeTimers();
    const onStateChange = vi.fn();
    mockedGetPracticeAssessment.mockResolvedValue(
      ok(makeAssessment({ status: "generating", questions: [], message: "Still working." })),
    );

    renderPracticeChild({ onStateChange });

    await flushPracticeTasks();
    await advancePracticePoll();

    expect(
      onStateChange.mock.calls.filter(([state]) => state.kind === "generating"),
    ).toHaveLength(1);
    expect(onStateChange).toHaveBeenCalledWith({
      kind: "generating",
      sectionId: "section-1",
      questionCount: 0,
      message: "Still working.",
      errorDetail: null,
      retryKind: null,
    });
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

  it("routes immediate structured provider readiness failures to Settings when starting questions", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(
      ok(makeAssessment({ status: "not_started", questions: undefined })),
    );
    mockedStartPracticeAssessment.mockResolvedValue({
      status: 503,
      ok: false,
      error: { detail: readinessDetail },
    });

    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("Your configured Ollama model is not present.");
    expect(screen.getByRole("link", { name: /open settings/i })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("keeps a failed assessment visible when retry hits a structured provider readiness failure", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(
      ok(makeAssessment({ status: "failed", questions: undefined, message: "Extraction failed." })),
    );
    mockedStartPracticeAssessment.mockResolvedValue({
      status: 503,
      ok: false,
      error: { detail: readinessDetail },
    });

    const user = userEvent.setup();
    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    expect(await screen.findByText("Extraction failed.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("Extraction failed.")).toBeInTheDocument();
    expect(screen.getByText("Your configured Ollama model is not present.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open settings/i })).toHaveAttribute(
      "href",
      "/settings",
    );
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

  it("does not notify the parent after unmount during start", async () => {
    const oldStart = deferred<Awaited<ReturnType<typeof startPracticeAssessment>>>();
    const onStateChange = vi.fn();
    mockedGetPracticeAssessment.mockResolvedValue(
      ok(makeAssessment({ status: "not_started", questions: undefined })),
    );
    mockedStartPracticeAssessment.mockReturnValue(oldStart.promise);

    const { unmount } = renderPracticeChild({ onStateChange });

    await waitFor(() => expect(mockedStartPracticeAssessment).toHaveBeenCalledTimes(1));
    onStateChange.mockClear();
    unmount();

    oldStart.resolve(ok(makeAssessment({ status: "generating", questions: undefined })));
    await flushPracticeTasks();

    expect(onStateChange).not.toHaveBeenCalled();
  });

  it("does not notify the parent for a stale start response after props change", async () => {
    const oldStart = deferred<Awaited<ReturnType<typeof startPracticeAssessment>>>();
    const onStateChange = vi.fn();
    mockedGetPracticeAssessment
      .mockResolvedValueOnce(ok(makeAssessment({ status: "not_started", questions: undefined })))
      .mockResolvedValueOnce(ok(makeAssessment({ section_id: "section-2" })));
    mockedStartPracticeAssessment.mockReturnValueOnce(oldStart.promise);

    const { rerender } = renderPracticeChild({ onStateChange, sectionId: "section-1" });

    await waitFor(() =>
      expect(mockedStartPracticeAssessment).toHaveBeenCalledWith("course-1", "section-1"),
    );
    rerender(practiceChild({ onStateChange, sectionId: "section-2" }));
    expect(await screen.findByText("Newton's second law")).toBeInTheDocument();
    onStateChange.mockClear();

    oldStart.resolve(ok(makeAssessment({ status: "generating", questions: undefined })));
    await flushPracticeTasks();

    expect(onStateChange).not.toHaveBeenCalledWith(
      expect.objectContaining({ sectionId: "section-1" }),
    );
  });

  it("shows failed extraction through ErrorBanner and retries with POST", async () => {
    mockedGetPracticeAssessment.mockResolvedValueOnce(
      ok(
        makeAssessment({
          status: "failed",
          questions: undefined,
          message: "Extraction failed for this section.",
        }),
      ),
    );
    mockedStartPracticeAssessment.mockResolvedValueOnce(ok(makeAssessment()));

    const user = userEvent.setup();
    render(<InlinePracticeAssessment courseId="course-1" sectionId="section-1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Extraction failed for this section.",
    );

    await user.click(screen.getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("Newton's second law")).toBeInTheDocument();
    expect(mockedGetPracticeAssessment).toHaveBeenCalledTimes(1);
    expect(mockedStartPracticeAssessment).toHaveBeenCalledWith("course-1", "section-1");
  });

  it("shows invalid model output as a retryable section failure", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(
      ok(
        makeAssessment({
          status: "failed",
          questions: [],
          message: "Parser dump: {\"raw\":\"not learner safe\"}",
          error_detail: {
            code: "invalid_model_output",
            failure_category: "structured_output_invalid",
            message: "The model returned an invalid question format.",
          },
        }),
      ),
    );

    renderPracticeChild({ retryVersion: 0 });

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/invalid question format/i);
    expect(banner).not.toHaveTextContent(/parser dump/i);
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
  });

  it("retries a failed extraction once when retryVersion increases", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(
      ok(makeAssessment({ status: "failed", questions: [], message: "Invalid format" })),
    );
    mockedStartPracticeAssessment.mockResolvedValue(ok(makeAssessment()));

    const view = renderPracticeChild({ retryVersion: 0 });
    await screen.findByText("Invalid format");
    view.rerender(practiceChild({ retryVersion: 1 }));

    await waitFor(() => expect(mockedStartPracticeAssessment).toHaveBeenCalledTimes(1));
  });

  it("does not retry a failed extraction when retryVersion is unchanged", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(
      ok(makeAssessment({ status: "failed", questions: [], message: "Invalid format" })),
    );

    const view = renderPracticeChild({ retryVersion: 0 });
    await screen.findByText("Invalid format");
    view.rerender(practiceChild({ retryVersion: 0 }));
    await flushPracticeTasks();

    expect(mockedStartPracticeAssessment).not.toHaveBeenCalled();
  });

  it("ignores retryVersion increases while ready", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(ok(makeAssessment()));

    const view = renderPracticeChild({ retryVersion: 0 });
    expect(await screen.findByText("Newton's second law")).toBeInTheDocument();
    view.rerender(practiceChild({ retryVersion: 1 }));
    await flushPracticeTasks();

    expect(mockedStartPracticeAssessment).not.toHaveBeenCalled();
    expect(mockedGetPracticeAssessment).toHaveBeenCalledTimes(1);
  });

  it("ignores retryVersion increases while generating", async () => {
    mockedGetPracticeAssessment.mockResolvedValue(
      ok(makeAssessment({ status: "generating", questions: [] })),
    );

    const view = renderPracticeChild({ retryVersion: 0 });
    expect(await screen.findByRole("status")).toHaveTextContent(/preparing practice questions/i);
    view.rerender(practiceChild({ retryVersion: 1 }));
    await flushPracticeTasks();

    expect(mockedStartPracticeAssessment).not.toHaveBeenCalled();
    expect(mockedGetPracticeAssessment).toHaveBeenCalledTimes(1);
  });

  it("reports load transport failures as reloadable parent state", async () => {
    const onStateChange = vi.fn();
    mockedGetPracticeAssessment.mockResolvedValueOnce(err(503));

    renderPracticeChild({ onStateChange });

    expect(await screen.findByRole("alert")).toHaveTextContent(/practice questions/i);
    expect(onStateChange).toHaveBeenCalledWith({
      kind: "failed",
      sectionId: "section-1",
      questionCount: 0,
      message: "Could not load practice questions.",
      errorDetail: null,
      retryKind: "reload",
    });
  });

  it("restarts extraction after a parent reload retry when the first not_started POST fails", async () => {
    mockedGetPracticeAssessment
      .mockResolvedValueOnce(ok(makeAssessment({ status: "not_started", questions: [] })))
      .mockResolvedValueOnce(ok(makeAssessment({ status: "not_started", questions: [] })));
    mockedStartPracticeAssessment
      .mockResolvedValueOnce(err(503))
      .mockResolvedValueOnce(ok(makeAssessment({ status: "generating", questions: [] })));

    const view = renderPracticeChild({ retryVersion: 0 });

    expect(await screen.findByRole("alert")).toHaveTextContent(/starting practice questions/i);
    expect(mockedStartPracticeAssessment).toHaveBeenCalledTimes(1);

    view.rerender(practiceChild({ retryVersion: 1 }));

    await waitFor(() => expect(mockedStartPracticeAssessment).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("status")).toHaveTextContent(/preparing practice questions/i);
  });

  it("reports extraction failures as restartable parent state", async () => {
    const onStateChange = vi.fn();
    mockedGetPracticeAssessment.mockResolvedValueOnce(
      ok(makeAssessment({ status: "failed", questions: [], message: "Invalid format" })),
    );

    renderPracticeChild({ onStateChange });

    await screen.findByText("Invalid format");
    expect(onStateChange).toHaveBeenCalledWith({
      kind: "failed",
      sectionId: "section-1",
      questionCount: 0,
      message: "Invalid format",
      errorDetail: null,
      retryKind: "restart",
    });
  });

  it("runs local and parent failed extraction retries through one active request guard", async () => {
    const restart = deferred<Awaited<ReturnType<typeof startPracticeAssessment>>>();
    mockedGetPracticeAssessment.mockResolvedValue(
      ok(makeAssessment({ status: "failed", questions: [], message: "Invalid format" })),
    );
    mockedStartPracticeAssessment.mockReturnValueOnce(restart.promise);

    const user = userEvent.setup();
    const view = renderPracticeChild({ retryVersion: 0 });
    await screen.findByText("Invalid format");

    await user.click(screen.getByRole("button", { name: /retry/i }));
    view.rerender(practiceChild({ retryVersion: 1 }));
    await flushPracticeTasks();

    expect(mockedStartPracticeAssessment).toHaveBeenCalledTimes(1);
    restart.resolve(ok(makeAssessment()));
    expect(await screen.findByText("Newton's second law")).toBeInTheDocument();
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
    expect(screen.getByText("Readiness needs more evidence")).toBeInTheDocument();
    expect(screen.getByText("0 evidence items")).toBeInTheDocument();
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

  it("ignores a stale submit response after props change", async () => {
    const oldSubmit = deferred<Awaited<ReturnType<typeof submitPracticeAnswer>>>();
    mockedGetPracticeAssessment
      .mockResolvedValueOnce(ok(makeAssessment()))
      .mockResolvedValueOnce(ok(makeAssessment({ section_id: "section-2" })));
    mockedSubmitPracticeAnswer.mockReturnValueOnce(oldSubmit.promise);

    const user = userEvent.setup();
    const { rerender } = render(
      <InlinePracticeAssessment courseId="course-1" sectionId="section-1" />,
    );

    await user.click(await screen.findByRole("button", { name: "4 N" }));
    expect(mockedSubmitPracticeAnswer).toHaveBeenCalledWith("course-1", "question-1", 0);

    rerender(<InlinePracticeAssessment courseId="course-1" sectionId="section-2" />);
    expect(await screen.findByText("Newton's second law")).toBeInTheDocument();

    oldSubmit.resolve(ok(makeSubmitAnswer()));
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.queryByText("Incorrect")).not.toBeInTheDocument();
    expect(screen.queryByText(/textbook relationship/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "4 N" })).not.toBeDisabled();
  });

  it("does not update state after unmount during submit", async () => {
    const oldSubmit = deferred<Awaited<ReturnType<typeof submitPracticeAnswer>>>();
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    mockedGetPracticeAssessment.mockResolvedValue(ok(makeAssessment()));
    mockedSubmitPracticeAnswer.mockReturnValueOnce(oldSubmit.promise);

    const user = userEvent.setup();
    const { unmount } = render(
      <InlinePracticeAssessment courseId="course-1" sectionId="section-1" />,
    );

    await user.click(await screen.findByRole("button", { name: "4 N" }));
    unmount();

    oldSubmit.resolve(ok(makeSubmitAnswer()));
    await act(async () => {
      await Promise.resolve();
    });

    expect(consoleError).not.toHaveBeenCalled();
    consoleError.mockRestore();
  });
});
