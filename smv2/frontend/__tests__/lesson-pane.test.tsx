import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LessonPane from "@/components/reader/LessonPane";
import {
  findActiveLessonJob,
  generateLesson,
  getJob,
  getLessonEstimate,
  getSection,
  type JobOut,
  type SectionDetailOut,
} from "@/lib/api/client";

import { ok } from "./support/api-result";
import { FakeEventSource } from "./support/fake-event-source";

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  getSection: vi.fn(),
  getLessonEstimate: vi.fn(),
  generateLesson: vi.fn(),
  findActiveLessonJob: vi.fn(),
  getJob: vi.fn(),
}));

const mockedGetSection = vi.mocked(getSection);
const mockedGetLessonEstimate = vi.mocked(getLessonEstimate);
const mockedGenerateLesson = vi.mocked(generateLesson);
const mockedFindActiveLessonJob = vi.mocked(findActiveLessonJob);
const mockedGetJob = vi.mocked(getJob);

function makeDetail(overrides: Partial<SectionDetailOut> = {}): SectionDetailOut {
  return {
    id: "sec-1",
    course_id: "course-1",
    title: "Consensus",
    order_index: 0,
    page_start: 1,
    page_end: 10,
    kind: "content",
    chapter_label: null,
    asset_id: null,
    body_md: "# Consensus\n\nSource text.",
    content_hash: "hash",
    lesson_md: null,
    lesson_status: "none",
    lesson_stale: false,
    lesson_model: null,
    lesson_prompt_version: null,
    extractor_version: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeJob(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: "job-1",
    type: "generate_lesson",
    status: "failed",
    payload: { section_id: "sec-1" },
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

describe("LessonPane", () => {
  let originalEventSource: typeof EventSource;

  beforeEach(() => {
    originalEventSource = globalThis.EventSource;
    FakeEventSource.instances = [];
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;

    mockedFindActiveLessonJob.mockResolvedValue(null);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.useRealTimers();
    globalThis.EventSource = originalEventSource;
  });

  it("shows the CTA with an estimate based on prior calls", async () => {
    mockedGetSection.mockResolvedValue(ok(makeDetail()));
    mockedGetLessonEstimate.mockResolvedValue({
      status: 200,
      ok: true,
      data: { est_seconds: 12, est_cost_usd: 0.0021, based_on_calls: 5 },
    });

    render(<LessonPane sectionId="sec-1" />);

    expect(await screen.findByRole("button", { name: /generate lesson/i })).toBeInTheDocument();
    expect(screen.getByText(/~12s/)).toBeInTheDocument();
    expect(screen.getByText(/based on 5 prior calls/i)).toBeInTheDocument();
  });

  it("shows a rough first-generation estimate when there's no call history", async () => {
    mockedGetSection.mockResolvedValue(ok(makeDetail()));
    mockedGetLessonEstimate.mockResolvedValue({
      status: 200,
      ok: true,
      data: { est_seconds: 30, est_cost_usd: null, based_on_calls: 0 },
    });

    render(<LessonPane sectionId="sec-1" />);

    expect(await screen.findByText(/first generation — rough estimate/i)).toBeInTheDocument();
  });

  it("clicking Generate lesson starts the job and renders live SSE progress", async () => {
    mockedGetSection.mockResolvedValue(ok(makeDetail()));
    mockedGetLessonEstimate.mockResolvedValue({
      status: 200,
      ok: true,
      data: { est_seconds: 30, est_cost_usd: 0.01, based_on_calls: 1 },
    });
    mockedGenerateLesson.mockResolvedValue(ok({ job_id: "job-1" }, 202));

    const user = userEvent.setup();
    render(<LessonPane sectionId="sec-1" />);

    await user.click(await screen.findByRole("button", { name: /generate lesson/i }));

    expect(mockedGenerateLesson).toHaveBeenCalledWith("sec-1", false);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(screen.getByRole("status")).toHaveTextContent(/preparing/i);

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "running",
        progress: { stage: "generating", pct: 10, message: "generating lesson for Consensus" },
      });
    });

    expect(screen.getByText(/generating/)).toBeInTheDocument();
    expect(screen.getByText(/10%/)).toBeInTheDocument();
  });

  it("shows the stalled message after 120s with no SSE event", async () => {
    mockedGetSection.mockResolvedValue(ok(makeDetail()));
    mockedGetLessonEstimate.mockResolvedValue({
      status: 200,
      ok: true,
      data: { est_seconds: 30, est_cost_usd: 0.01, based_on_calls: 1 },
    });
    mockedGenerateLesson.mockResolvedValue(ok({ job_id: "job-1" }, 202));

    vi.useFakeTimers();
    render(<LessonPane sectionId="sec-1" />);

    await act(async () => {
      for (let i = 0; i < 10; i++) await Promise.resolve();
    });
    fireEvent.click(screen.getByRole("button", { name: /generate lesson/i }));
    await act(async () => {
      for (let i = 0; i < 10; i++) await Promise.resolve();
    });

    expect(FakeEventSource.instances).toHaveLength(1);
    act(() => {
      vi.advanceTimersByTime(120_000);
    });

    expect(screen.getByText(/still working/i)).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("renders the ready lesson with the full 'Generated · model · prompt version' label, and Regenerate confirms before sending force=true", async () => {
    mockedGetSection.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeDetail({
        lesson_status: "ready",
        lesson_md: "# The Lesson\n\nContent.",
        lesson_model: "claude-fable-5",
        lesson_prompt_version: "v3",
      }),
    });
    mockedGetLessonEstimate.mockResolvedValue({
      status: 200,
      ok: true,
      data: { est_seconds: 20, est_cost_usd: 0.02, based_on_calls: 3 },
    });
    mockedGenerateLesson.mockResolvedValue(ok({ job_id: "job-2" }, 202));

    const user = userEvent.setup();
    render(<LessonPane sectionId="sec-1" />);

    expect(await screen.findByText("Generated · claude-fable-5 · prompt v3")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /the lesson/i })).toBeInTheDocument();
    expect(screen.queryByText(/prompt updated since generation/i)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /regenerate/i }));
    expect(mockedGenerateLesson).not.toHaveBeenCalled();
    expect(screen.getByText(/regenerating replaces the current lesson/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /confirm/i }));
    expect(mockedGenerateLesson).toHaveBeenCalledWith("sec-1", true);
  });

  it("falls back to the plain 'Generated' label when model/prompt version aren't set", async () => {
    mockedGetSection.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeDetail({
        lesson_status: "ready",
        lesson_md: "Content.",
        lesson_model: null,
        lesson_prompt_version: null,
      }),
    });
    mockedGetLessonEstimate.mockResolvedValue({
      status: 200,
      ok: true,
      data: { est_seconds: 20, est_cost_usd: 0.02, based_on_calls: 3 },
    });

    render(<LessonPane sectionId="sec-1" />);

    expect(await screen.findByText("Generated")).toBeInTheDocument();
  });

  it("shows the stale badge next to Regenerate when lesson_stale is true", async () => {
    mockedGetSection.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeDetail({ lesson_status: "ready", lesson_md: "Content.", lesson_stale: true }),
    });
    mockedGetLessonEstimate.mockResolvedValue({
      status: 200,
      ok: true,
      data: { est_seconds: 20, est_cost_usd: 0.02, based_on_calls: 3 },
    });

    render(<LessonPane sectionId="sec-1" />);

    expect(await screen.findByText(/prompt updated since generation/i)).toBeInTheDocument();
  });

  it("shows a failed state with a retry that sends force=true", async () => {
    mockedGetSection.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeDetail({ lesson_status: "failed" }),
    });
    mockedGetLessonEstimate.mockResolvedValue({
      status: 200,
      ok: true,
      data: { est_seconds: 20, est_cost_usd: 0.02, based_on_calls: 3 },
    });
    mockedGenerateLesson.mockResolvedValue(ok({ job_id: "job-3" }, 202));

    const user = userEvent.setup();
    render(<LessonPane sectionId="sec-1" />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/generation failed\./i);

    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(mockedGenerateLesson).toHaveBeenCalledWith("sec-1", true);
  });

  it("shows the job's error text verbatim when a freshly-started generation job fails", async () => {
    mockedGetSection
      .mockResolvedValueOnce(ok(makeDetail({ lesson_status: "none" })))
      .mockResolvedValueOnce(ok(makeDetail({ lesson_status: "failed" })));
    mockedGetLessonEstimate.mockResolvedValue(
      ok({ est_seconds: 30, est_cost_usd: 0.01, based_on_calls: 1 }),
    );
    mockedGenerateLesson.mockResolvedValue(ok({ job_id: "job-9" }, 202));
    mockedGetJob.mockResolvedValue(
      ok(makeJob({
        id: "job-9",
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
    render(<LessonPane sectionId="sec-1" />);

    await user.click(await screen.findByRole("button", { name: /generate lesson/i }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-9",
        status: "failed",
        progress: null,
      });
    });

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/generation failed: anthropic_api_key is not configured/i);
    expect(screen.getByRole("link", { name: /open settings/i })).toHaveAttribute("href", "/settings");
  });

  it("bubbles the effective status up via onStatusChange", async () => {
    mockedGetSection.mockResolvedValue({
      status: 200,
      ok: true,
      data: makeDetail({ lesson_status: "ready", lesson_md: "Content." }),
    });
    mockedGetLessonEstimate.mockResolvedValue({
      status: 200,
      ok: true,
      data: { est_seconds: 20, est_cost_usd: 0.02, based_on_calls: 3 },
    });
    const onStatusChange = vi.fn();

    render(<LessonPane sectionId="sec-1" onStatusChange={onStatusChange} />);

    await waitFor(() => expect(onStatusChange).toHaveBeenCalledWith("ready"));
  });
});
