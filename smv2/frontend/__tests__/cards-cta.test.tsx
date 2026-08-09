import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CardsCTA from "@/components/reader/CardsCTA";
import {
  findActiveCardsJob,
  generateCards,
  cancelJob,
  getJob,
  listCards,
  type ApiResult,
  type CardOut,
  type GenerateCardsOut,
  type JobOut,
} from "@/lib/api/client";

import { err, ok } from "./support/api-result";
import { FakeEventSource } from "./support/fake-event-source";

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  listCards: vi.fn(),
  generateCards: vi.fn(),
  findActiveCardsJob: vi.fn(),
  cancelJob: vi.fn(),
  getJob: vi.fn(),
}));

const mockedListCards = vi.mocked(listCards);
const mockedGenerateCards = vi.mocked(generateCards);
const mockedCancelJob = vi.mocked(cancelJob);
const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);
const mockedGetJob = vi.mocked(getJob);

function makeCard(overrides: Partial<CardOut> = {}): CardOut {
  return {
    id: "card-1",
    section_id: "sec-1",
    front_md: "Front",
    back_md: "Back",
    position: 0,
    origin: "generated",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeJob(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: "job-1",
    type: "generate_cards",
    status: "running",
    payload: { section_id: "sec-1" },
    result: null,
    progress: null,
    error: null,
    error_detail: null,
    retryable: true,
    attempts: 0,
    cancel_requested_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("CardsCTA", () => {
  let originalEventSource: typeof EventSource;

  beforeEach(() => {
    originalEventSource = globalThis.EventSource;
    FakeEventSource.instances = [];
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
    mockedFindActiveCardsJob.mockResolvedValue(null);
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    globalThis.EventSource = originalEventSource;
  });

  it("shows 'Generate flashcards' with no count when the section has no cards yet", async () => {
    mockedListCards.mockResolvedValue(ok([]));

    render(<CardsCTA sectionId="sec-1" />);

    expect(await screen.findByRole("button", { name: /generate flashcards/i })).toBeInTheDocument();
    expect(screen.queryByText(/flashcard/i, { selector: "span" })).not.toBeInTheDocument();
  });

  it("shows the card count and 'Generate more flashcards' when cards already exist", async () => {
    mockedListCards.mockResolvedValue(ok([makeCard({ id: "c1" }), makeCard({ id: "c2" })]));

    render(<CardsCTA sectionId="sec-1" />);

    expect(await screen.findByText("2 flashcards")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate more flashcards/i })).toBeInTheDocument();
  });

  it("clicking Generate flashcards starts the job and renders live SSE progress, then refetches on settle", async () => {
    mockedListCards.mockResolvedValueOnce(ok([])).mockResolvedValueOnce(ok([makeCard()]));
    mockedGenerateCards.mockResolvedValue(ok({ job_id: "job-1" }, 202));

    const user = userEvent.setup();
    render(<CardsCTA sectionId="sec-1" />);

    await user.click(await screen.findByRole("button", { name: /generate flashcards/i }));
    expect(mockedGenerateCards).toHaveBeenCalledWith("sec-1");

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "succeeded",
        progress: { stage: "done", pct: 100, message: "done" },
      });
    });

    expect(await screen.findByText("1 flashcard")).toBeInTheDocument();
  });

  it("rediscovers an in-flight job on mount and shows the generating state without a click", async () => {
    mockedListCards.mockResolvedValue(ok([]));
    mockedFindActiveCardsJob.mockResolvedValue(makeJob({ id: "job-existing" }));

    render(<CardsCTA sectionId="sec-1" />);

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(screen.queryByRole("button", { name: /generate flashcards/i })).not.toBeInTheDocument();
  });

  it("resyncs to the in-flight job instead of erroring on a 409", async () => {
    mockedListCards.mockResolvedValue(ok([]));
    mockedFindActiveCardsJob
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce(makeJob({ id: "job-conflict" }));
    mockedGenerateCards.mockResolvedValue(err(409));

    const user = userEvent.setup();
    render(<CardsCTA sectionId="sec-1" />);

    await user.click(await screen.findByRole("button", { name: /generate flashcards/i }));

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(screen.queryByText(/failed/i)).not.toBeInTheDocument();
  });

  it("routes immediate structured provider readiness failures to Settings without starting a job stream", async () => {
    mockedListCards.mockResolvedValue(ok([]));
    mockedGenerateCards.mockResolvedValue({
      status: 503,
      ok: false,
      error: {
        detail: {
          code: "llm_readiness_unavailable",
          failure_category: "missing_credentials",
          message: "LLM provider is not ready",
          remediation: "Configure an available model in Settings.",
        },
      },
    } satisfies ApiResult<GenerateCardsOut>);

    const user = userEvent.setup();
    render(<CardsCTA sectionId="sec-1" />);

    await user.click(await screen.findByRole("button", { name: /generate flashcards/i }));

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("LLM provider is not ready");
    expect(screen.getByRole("link", { name: /open settings/i })).toHaveAttribute("href", "/settings");
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(mockedGetJob).not.toHaveBeenCalled();
  });

  it("routes structured provider readiness failures to Settings and hides retry", async () => {
    mockedListCards.mockResolvedValue(ok([]));
    mockedGenerateCards.mockResolvedValueOnce(ok({ job_id: "job-1" }, 202));
    mockedGetJob.mockResolvedValue(
      ok(makeJob({
        id: "job-1",
        status: "failed",
        error: "Display-only provider failure",
        error_detail: {
          code: "llm_readiness_unavailable",
          failure_category: "missing_credentials",
          message: "LLM provider is not ready",
          remediation: "Add an Anthropic key.",
        },
      })),
    );

    const user = userEvent.setup();
    render(<CardsCTA sectionId="sec-1" />);

    await user.click(await screen.findByRole("button", { name: /generate flashcards/i }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "failed",
        progress: null,
      });
    });

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/generation failed: display-only provider failure/i);
    expect(screen.getByRole("link", { name: /open settings/i })).toHaveAttribute("href", "/settings");
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(mockedGenerateCards).toHaveBeenCalledTimes(1);
  });

  it("routes structured non-readiness failures to the exact job id and keeps safe retry visible", async () => {
    mockedListCards.mockResolvedValue(ok([]));
    mockedGenerateCards
      .mockResolvedValueOnce(ok({ job_id: "job-404" }, 202))
      .mockResolvedValueOnce(ok({ job_id: "job-405" }, 202));
    mockedGetJob.mockResolvedValue(
      ok(makeJob({
        id: "job-404",
        status: "failed",
        error: "Worker crashed",
        error_detail: { code: "job_failed", failure_category: "worker_error", message: "Worker crashed" },
      })),
    );

    const user = userEvent.setup();
    render(<CardsCTA sectionId="sec-1" />);

    await user.click(await screen.findByRole("button", { name: /generate flashcards/i }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-404",
        status: "failed",
        progress: null,
      });
    });

    expect(await screen.findByRole("link", { name: /view job details/i })).toHaveAttribute("href", "/jobs?job=job-404");
    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(mockedGenerateCards).toHaveBeenCalledTimes(2);
  });

  it("cancels an in-flight generation job once from the shared progress control", async () => {
    mockedListCards.mockResolvedValue(ok([]));
    mockedGenerateCards.mockResolvedValue(ok({ job_id: "job-1" }, 202));
    mockedCancelJob.mockResolvedValue(ok(makeJob({ id: "job-1", status: "cancelled" })));

    const user = userEvent.setup();
    render(<CardsCTA sectionId="sec-1" />);

    await user.click(await screen.findByRole("button", { name: /generate flashcards/i }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    await user.click(screen.getByRole("button", { name: /cancel generation/i }));

    expect(mockedCancelJob).toHaveBeenCalledWith("job-1");
    expect(mockedCancelJob).toHaveBeenCalledTimes(1);
  });
});
