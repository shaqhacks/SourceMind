import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import QuizzesPanel from "@/components/reader/QuizzesPanel";
import { generateTest, listTests, type TestAttemptSummaryOut } from "@/lib/api/client";

import { ok } from "./support/api-result";
import { FakeEventSource } from "./support/fake-event-source";

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  listTests: vi.fn(),
  generateTest: vi.fn(),
}));

const mockedListTests = vi.mocked(listTests);
const mockedGenerateTest = vi.mocked(generateTest);

function makeAttempt(overrides: Partial<TestAttemptSummaryOut> = {}): TestAttemptSummaryOut {
  return {
    id: "attempt-1",
    course_id: "course-1",
    score: null,
    question_count: 5,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("QuizzesPanel", () => {
  let originalEventSource: typeof EventSource;

  beforeEach(() => {
    originalEventSource = globalThis.EventSource;
    FakeEventSource.instances = [];
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    globalThis.EventSource = originalEventSource;
  });

  it("opening the panel loads and shows the attempt list", async () => {
    mockedListTests.mockResolvedValue({
      status: 200,
      ok: true,
      data: [makeAttempt({ id: "a1", score: 0.8 }), makeAttempt({ id: "a2", score: null })],
    });
    const user = userEvent.setup();

    render(<QuizzesPanel courseId="course-1" />);
    await user.click(screen.getByRole("button", { name: /^quizzes$/i }));

    expect(await screen.findByText("80%")).toBeInTheDocument();
    expect(screen.getByText("In progress")).toBeInTheDocument();
  });

  it("names the next action when the course has no quizzes yet", async () => {
    mockedListTests.mockResolvedValue(ok([]));
    const user = userEvent.setup();

    render(<QuizzesPanel courseId="course-1" />);
    await user.click(screen.getByRole("button", { name: /^quizzes$/i }));

    expect(await screen.findByText(/no quizzes yet — generate one above/i)).toBeInTheDocument();
  });

  it("clicking an attempt navigates to its taking/review page and closes the panel", async () => {
    mockedListTests.mockResolvedValue({
      status: 200,
      ok: true,
      data: [makeAttempt({ id: "attempt-9", score: 0.6 })],
    });
    const user = userEvent.setup();

    render(<QuizzesPanel courseId="course-1" />);
    await user.click(screen.getByRole("button", { name: /^quizzes$/i }));
    await user.click(await screen.findByText("60%"));

    expect(mockPush).toHaveBeenCalledWith("/course/course-1/test/attempt-9");
    expect(screen.queryByRole("dialog", { name: /quizzes/i })).not.toBeInTheDocument();
  });

  it("'Generate quiz' starts a job, renders SSE progress, and refetches the list on settle", async () => {
    mockedListTests
      .mockResolvedValueOnce(ok([]))
      .mockResolvedValueOnce(ok([makeAttempt({ id: "new-attempt" })]));
    mockedGenerateTest.mockResolvedValue(ok({ job_id: "job-1" }, 202));
    const user = userEvent.setup();

    render(<QuizzesPanel courseId="course-1" />);
    await user.click(screen.getByRole("button", { name: /^quizzes$/i }));
    await screen.findByText(/no quizzes yet/i);

    await user.click(screen.getByRole("button", { name: /generate quiz/i }));
    expect(mockedGenerateTest).toHaveBeenCalledWith("course-1");

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "succeeded",
        progress: { stage: "done", pct: 100, message: "done" },
      });
    });

    expect(await screen.findByText("In progress")).toBeInTheDocument();
  });
});
