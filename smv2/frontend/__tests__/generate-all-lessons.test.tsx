import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GenerateAllLessons from "@/components/reader/GenerateAllLessons";
import { generateAllLessons, getJob, type ApiErrorDetail, type JobOut } from "@/lib/api/client";

import { FakeEventSource } from "./support/fake-event-source";

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  generateAllLessons: vi.fn(),
  getJob: vi.fn(),
}));

const mockedGenerateAllLessons = vi.mocked(generateAllLessons);
const mockedGetJob = vi.mocked(getJob);

const readinessDetail: ApiErrorDetail = {
  code: "llm_readiness_unavailable",
  failure_category: "ollama_model_unavailable",
  message: "Your configured Ollama model is not present.",
  remediation: "Open Settings and select a currently installed model.",
};

function makeJob(id: string, sectionId: string): JobOut {
  return {
    id,
    type: "generate_lesson",
    status: "queued",
    payload: { section_id: sectionId },
    result: null,
    progress: null,
    error: null,
    error_detail: null,
    retryable: true,
    attempts: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("GenerateAllLessons", () => {
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

  it("counts two jobs down to done as their SSE streams settle, and reports each section", async () => {
    mockedGenerateAllLessons.mockResolvedValue({
      status: 202,
      ok: true,
      data: { job_ids: ["job-1", "job-2"], skipped: 1 },
    });
    mockedGetJob.mockImplementation((jobId: string) =>
      Promise.resolve({
        status: 200,
        ok: true,
        data: makeJob(jobId, jobId === "job-1" ? "sec-1" : "sec-2"),
      }),
    );

    const onSectionSettled = vi.fn();
    const user = userEvent.setup();
    render(<GenerateAllLessons courseId="course-1" onSectionSettled={onSectionSettled} />);

    await user.click(screen.getByRole("button", { name: /generate all lessons/i }));

    expect(mockedGenerateAllLessons).toHaveBeenCalledWith("course-1");
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
    expect(screen.getByRole("button", { name: /generating 0 of 2/i })).toBeInTheDocument();

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "succeeded",
        progress: { stage: "done", pct: 100, message: "lesson ready" },
      });
    });

    expect(onSectionSettled).toHaveBeenCalledWith("sec-1", "ready");
    expect(screen.getByRole("button", { name: /generating 1 of 2/i })).toBeInTheDocument();

    act(() => {
      FakeEventSource.instances[1].emit("update", { id: "job-2", status: "failed", progress: null });
    });

    expect(onSectionSettled).toHaveBeenCalledWith("sec-2", "failed");
    expect(screen.getByRole("button", { name: /^generate all lessons$/i })).toBeInTheDocument();
  });

  it("shows how many sections were already generated and skipped", async () => {
    mockedGenerateAllLessons.mockResolvedValue({
      status: 202,
      ok: true,
      data: { job_ids: [], skipped: 4 },
    });

    const user = userEvent.setup();
    render(<GenerateAllLessons courseId="course-1" onSectionSettled={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /generate all lessons/i }));

    expect(await screen.findByText(/4 already generated/i)).toBeInTheDocument();
  });

  it("shows a retryable error when starting the batch fails", async () => {
    mockedGenerateAllLessons.mockResolvedValue({ status: 500, ok: false });

    const user = userEvent.setup();
    render(<GenerateAllLessons courseId="course-1" onSectionSettled={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /generate all lessons/i }));

    expect(await screen.findByText(/starting generation failed/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /view job details/i })).toHaveAttribute("href", "/jobs");
  });

  it("routes immediate structured provider readiness failures to Settings without starting job streams", async () => {
    mockedGenerateAllLessons.mockResolvedValue({
      status: 503,
      ok: false,
      error: { detail: readinessDetail },
    });

    const user = userEvent.setup();
    render(<GenerateAllLessons courseId="course-1" onSectionSettled={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: /generate all lessons/i }));

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
