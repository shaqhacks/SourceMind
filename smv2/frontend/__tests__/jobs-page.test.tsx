import { Suspense } from "react";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import JobsPage from "@/app/jobs/page";
import { getLlmStatus, listJobs, retryJob, type JobOut } from "@/lib/api/client";

let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams,
}));

vi.mock("@/lib/api/client", () => ({
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  getLlmStatus: vi.fn(),
  listJobs: vi.fn(),
  retryJob: vi.fn(),
}));

const mockedGetLlmStatus = vi.mocked(getLlmStatus);
const mockedListJobs = vi.mocked(listJobs);
const mockedRetryJob = vi.mocked(retryJob);

function makeJob(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: "job-1",
    type: "generate_lesson",
    status: "failed",
    payload: { course_id: "course-1", section_id: "sec-1" },
    result: null,
    progress: null,
    error: "LLM unavailable",
    error_detail: null,
    attempts: 1,
    cancel_requested_at: null,
    retryable: true,
    created_at: "2026-08-05T12:00:00Z",
    updated_at: "2026-08-05T12:03:00Z",
    ...overrides,
  };
}

describe("JobsPage", () => {
  beforeEach(() => {
    mockSearchParams = new URLSearchParams();
    mockedGetLlmStatus.mockResolvedValue({
      status: 200,
      ok: true,
      data: {
        provider: "anthropic",
        model: "claude-sonnet",
        configured: true,
        available: true,
        capabilities: { completion: true, embeddings: false },
        last_checked_at: null,
        failure_category: null,
        remediation: null,
      },
    });
    mockedRetryJob.mockResolvedValue({ status: 202, ok: true, data: makeJob({ id: "retry-1", status: "queued" }) });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("wraps the search-param client in Suspense for static rendering", () => {
    const element = JobsPage();

    expect(element.type).toBe(Suspense);
  });

  it("groups active and recent jobs by course and type with course and section links", async () => {
    mockedListJobs.mockResolvedValue({
      status: 200,
      ok: true,
      data: [
        makeJob({ id: "job-active", status: "running", type: "generate_cards", payload: { course_id: "course-1", section_id: "sec-2" } }),
        makeJob({ id: "job-recent", status: "succeeded", type: "generate_lesson", payload: { course_id: "course-1", section_id: "sec-1" } }),
        makeJob({ id: "job-other", status: "failed", type: "ingest", payload: { course_id: "course-2" }, retryable: false }),
      ],
    });

    render(<JobsPage />);

    expect(await screen.findByRole("heading", { name: "Jobs" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /course-1/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /generate cards/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /generate lesson/i })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /open course course-1/i })[0]).toHaveAttribute("href", "/course/course-1");
    expect(screen.getByRole("link", { name: /open section sec-2/i })).toHaveAttribute("href", "/course/course-1/read?section=sec-2");
  });

  it("highlights the job requested by query string", async () => {
    mockSearchParams = new URLSearchParams({ job: "job-target" });
    mockedListJobs.mockResolvedValue({ status: 200, ok: true, data: [makeJob({ id: "job-target" })] });

    render(<JobsPage />);

    const article = await screen.findByTestId("job-job-target");
    expect(article).toHaveAttribute("aria-current", "true");
    expect(article.className).toContain("ring");
  });

  it("shows retry only for retryable failed jobs and refreshes after retry", async () => {
    mockedListJobs
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        data: [
          makeJob({ id: "retryable", retryable: true, status: "failed" }),
          makeJob({ id: "not-retryable", retryable: false, status: "failed", type: "ingest" }),
        ],
      })
      .mockResolvedValueOnce({ status: 200, ok: true, data: [makeJob({ id: "new-job", status: "queued" })] });

    const user = userEvent.setup();
    render(<JobsPage />);

    const retryable = await screen.findByTestId("job-retryable");
    expect(within(retryable).getByRole("button", { name: /retry/i })).toBeInTheDocument();
    expect(within(screen.getByTestId("job-not-retryable")).queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();

    await user.click(within(retryable).getByRole("button", { name: /retry/i }));

    expect(mockedRetryJob).toHaveBeenCalledWith("retryable");
    await waitFor(() => expect(mockedListJobs).toHaveBeenCalledTimes(2));
  });

  it("hides job retry actions when LLM readiness is unavailable", async () => {
    mockedGetLlmStatus.mockResolvedValue({
      status: 200,
      ok: true,
      data: {
        provider: "anthropic",
        model: "claude-sonnet",
        configured: false,
        available: false,
        capabilities: { completion: false, embeddings: false },
        last_checked_at: null,
        failure_category: "missing_credentials",
        remediation: "Add an Anthropic key.",
      },
    });
    mockedListJobs.mockResolvedValue({
      status: 200,
      ok: true,
      data: [makeJob({ id: "retryable", retryable: true, status: "failed" })],
    });

    render(<JobsPage />);

    const retryable = await screen.findByTestId("job-retryable");
    expect(within(retryable).queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /open settings/i })).toHaveAttribute("href", "/settings");
  });

  it("hides retry while readiness is still loading", async () => {
    mockedGetLlmStatus.mockReturnValue(new Promise(() => {}));
    mockedListJobs.mockResolvedValue({
      status: 200,
      ok: true,
      data: [makeJob({ id: "retryable", retryable: true, status: "failed" })],
    });

    render(<JobsPage />);

    const retryable = await screen.findByTestId("job-retryable");
    expect(within(retryable).queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(within(retryable).getByText(/checking provider readiness/i)).toBeInTheDocument();
  });

  it("hides retry when readiness cannot be fetched", async () => {
    mockedGetLlmStatus.mockResolvedValue({ status: 500, ok: false });
    mockedListJobs.mockResolvedValue({
      status: 200,
      ok: true,
      data: [makeJob({ id: "retryable", retryable: true, status: "failed" })],
    });

    render(<JobsPage />);

    const retryable = await screen.findByTestId("job-retryable");
    expect(within(retryable).queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(within(retryable).getByText(/provider readiness unavailable/i)).toBeInTheDocument();
  });
});
