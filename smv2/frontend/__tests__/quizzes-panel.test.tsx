import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import QuizzesPanel from "@/components/reader/QuizzesPanel";
import {
  type ApiErrorDetail,
  generateTest,
  getJob,
  listTests,
  type JobOut,
  type TestAttemptSummaryOut,
  type TestSummaryOut,
} from "@/lib/api/client";

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
  getJob: vi.fn(),
}));

const mockedListTests = vi.mocked(listTests);
const mockedGenerateTest = vi.mocked(generateTest);
const mockedGetJob = vi.mocked(getJob);

const readinessDetail: ApiErrorDetail = {
  code: "llm_readiness_unavailable",
  failure_category: "ollama_model_unavailable",
  message: "Your configured Ollama model is not present.",
  remediation: "Open Settings and select a currently installed model.",
};

function makeAttemptSummary(
  overrides: Partial<TestAttemptSummaryOut> = {},
): TestAttemptSummaryOut {
  return {
    id: "attempt-1",
    score: null,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

// One test/deck with a single (latest) attempt, the common case in these
// tests — QuizzesPanel only ever surfaces each test's newest attempt.
function makeTest(overrides: Partial<TestSummaryOut> = {}): TestSummaryOut {
  return {
    id: "test-1",
    chapter_label: null,
    course_id: "course-1",
    question_count: 5,
    created_at: "2026-01-01T00:00:00Z",
    attempts: [makeAttemptSummary()],
    ...overrides,
  };
}

function makeJob(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: "job-1",
    type: "generate_test",
    status: "failed",
    payload: { course_id: "course-1" },
    result: null,
    progress: null,
    error: null,
    error_detail: null,
    retryable: true,
    attempts: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
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
      data: [
        makeTest({ id: "t1", attempts: [makeAttemptSummary({ id: "a1", score: 0.8 })] }),
        makeTest({ id: "t2", attempts: [makeAttemptSummary({ id: "a2", score: null })] }),
      ],
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
      data: [makeTest({ attempts: [makeAttemptSummary({ id: "attempt-9", score: 0.6 })] })],
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
      .mockResolvedValueOnce(ok([makeTest({ attempts: [makeAttemptSummary({ id: "new-attempt" })] })]));
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

  it("shows the job's error text and a retry when quiz generation fails, instead of silently resetting to idle", async () => {
    mockedListTests.mockResolvedValue(ok([]));
    mockedGenerateTest
      .mockResolvedValueOnce(ok({ job_id: "job-1" }, 202))
      .mockResolvedValueOnce(ok({ job_id: "job-2" }, 202));
    mockedGetJob.mockResolvedValue(
      ok(makeJob({
        id: "job-1",
        error: "ANTHROPIC_API_KEY is not configured",
        error_detail: {
          code: "llm_readiness_unavailable",
          failure_category: "missing_credentials",
          message: "LLM provider is not ready",
          remediation: "Add an Anthropic key.",
        },
      })),
    );
    const user = userEvent.setup();

    render(<QuizzesPanel courseId="course-1" />);
    await user.click(screen.getByRole("button", { name: /^quizzes$/i }));
    await screen.findByText(/no quizzes yet/i);

    await user.click(screen.getByRole("button", { name: /generate quiz/i }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "failed",
        progress: null,
      });
    });

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/generation failed: anthropic_api_key is not configured/i);
    expect(screen.getByRole("link", { name: /open settings/i })).toHaveAttribute("href", "/settings");

    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(mockedGenerateTest).toHaveBeenCalledTimes(1);
  });

  it("routes immediate structured provider readiness failures to Settings without starting a job stream", async () => {
    mockedGenerateTest.mockReset();
    mockedListTests.mockResolvedValue(ok([]));
    mockedGenerateTest.mockResolvedValue({
      status: 503,
      ok: false,
      error: { detail: readinessDetail },
    });
    const user = userEvent.setup();

    render(<QuizzesPanel courseId="course-1" />);
    await user.click(screen.getByRole("button", { name: /^quizzes$/i }));
    await screen.findByText(/no quizzes yet/i);

    await user.click(screen.getByRole("button", { name: /generate quiz/i }));

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("Your configured Ollama model is not present.");
    expect(screen.getByRole("link", { name: /open settings/i })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(mockedGetJob).not.toHaveBeenCalled();
  });
});
