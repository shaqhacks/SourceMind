import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ChapterDeckCard from "@/components/flashcards/ChapterDeckCard";
import {
  findActiveCardsJob,
  generateCards,
  getJob,
  type ApiResult,
  type GenerateCardsOut,
} from "@/lib/api/client";

import { FakeEventSource } from "./support/fake-event-source";

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  findActiveCardsJob: vi.fn(),
  generateCards: vi.fn(),
  getJob: vi.fn(),
}));

const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);
const mockedGenerateCards = vi.mocked(generateCards);
const mockedGetJob = vi.mocked(getJob);

const providerReadinessError = {
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
} satisfies ApiResult<GenerateCardsOut>;

describe("ChapterDeckCard", () => {
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

  it("shows a no-content message and no Generate button for a chapter with no content sections", () => {
    render(
      <ChapterDeckCard
        courseId="course-1"
        chapterNumber={1}
        title="Front Matter Only"
        sectionIds={[]}
        cards={[]}
        dueCount={0}
        isBrowsed={false}
        onBrowse={vi.fn()}
      />,
    );

    expect(
      screen.getByText(/this chapter has no content section to generate cards from/i),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /generate cards/i })).not.toBeInTheDocument();
  });

  it("routes immediate structured provider readiness failures to Settings without starting a job stream", async () => {
    mockedGenerateCards.mockResolvedValue(providerReadinessError);

    const user = userEvent.setup();
    render(
      <ChapterDeckCard
        courseId="course-1"
        chapterNumber={2}
        title="Cardable Chapter"
        sectionIds={["sec-1"]}
        cards={[]}
        dueCount={0}
        isBrowsed={false}
        onBrowse={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /generate cards/i }));

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("LLM provider is not ready");
    expect(screen.getByRole("link", { name: /open settings/i })).toHaveAttribute("href", "/settings");
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(mockedGetJob).not.toHaveBeenCalled();
  });

  it("routes queued section structured provider readiness failures to Settings without starting another job stream", async () => {
    mockedGenerateCards
      .mockResolvedValueOnce({ status: 202, ok: true, data: { job_id: "job-1" } })
      .mockResolvedValueOnce(providerReadinessError);

    const user = userEvent.setup();
    render(
      <ChapterDeckCard
        courseId="course-1"
        chapterNumber={3}
        title="Multi-section Chapter"
        sectionIds={["sec-1", "sec-2"]}
        cards={[]}
        dueCount={0}
        isBrowsed={false}
        onBrowse={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: /generate cards/i }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "succeeded",
        progress: { stage: "done", pct: 100, message: "done" },
      });
    });

    await waitFor(() => expect(mockedGenerateCards).toHaveBeenCalledWith("sec-2"));
    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent("LLM provider is not ready");
    expect(screen.getByRole("link", { name: /open settings/i })).toHaveAttribute("href", "/settings");
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(mockedGetJob).not.toHaveBeenCalled();
  });
});
