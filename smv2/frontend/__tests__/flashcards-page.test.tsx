import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import FlashcardsClient from "@/components/flashcards/FlashcardsClient";
import {
  findActiveCardsJob,
  generateCards,
  getJob,
  getReviewQueue,
  getReviewSummary,
  listCards,
  listChapters,
  listCourses,
  type CardOut,
  type ChapterOut,
  type CourseOut,
  type JobOut,
  type ReviewQueueCardOut,
  type ReviewSummaryOut,
} from "@/lib/api/client";

import { err, ok } from "./support/api-result";
import { FakeEventSource } from "./support/fake-event-source";

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  listCourses: vi.fn(),
  listChapters: vi.fn(),
  listCards: vi.fn(),
  getReviewQueue: vi.fn(),
  getReviewSummary: vi.fn(),
  generateCards: vi.fn(),
  findActiveCardsJob: vi.fn(),
  getJob: vi.fn(),
}));

const mockedListCourses = vi.mocked(listCourses);
const mockedListChapters = vi.mocked(listChapters);
const mockedListCards = vi.mocked(listCards);
const mockedGetReviewQueue = vi.mocked(getReviewQueue);
const mockedGetReviewSummary = vi.mocked(getReviewSummary);
const mockedGenerateCards = vi.mocked(generateCards);
const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);
const mockedGetJob = vi.mocked(getJob);

function makeCourse(overrides: Partial<CourseOut> = {}): CourseOut {
  return {
    id: "course-1",
    title: "Course One",
    status: "ready",
    section_count: 3,
    failed_asset_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    progress: null,
    ...overrides,
  };
}

function makeChapter(overrides: Partial<ChapterOut> = {}): ChapterOut {
  return {
    chapter_label: "Chapter",
    section_ids: [],
    practice_section_ids: [],
    answers_section_ids: [],
    test_stats: null,
    ...overrides,
  };
}

function makeCard(overrides: Partial<CardOut> = {}): CardOut {
  return {
    id: "card",
    section_id: "sec",
    front_md: "Front",
    back_md: "Back",
    position: 0,
    origin: "generated",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeQueueCard(overrides: Partial<ReviewQueueCardOut> = {}): ReviewQueueCardOut {
  return {
    id: "card",
    section_id: "sec",
    front_md: "Front",
    back_md: "Back",
    due_at: null,
    is_new: true,
    interval_days: 0,
    ease: 2.5,
    reps: 0,
    ...overrides,
  };
}

function makeSummary(overrides: Partial<ReviewSummaryOut> = {}): ReviewSummaryOut {
  return {
    backlog_warning: false,
    courses: [],
    daily_throughput: 10,
    due_total: 0,
    ...overrides,
  };
}

function makeJob(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: "job-1",
    type: "generate_cards",
    status: "running",
    payload: { section_id: "sec-2" },
    result: null,
    progress: null,
    error: null,
    attempts: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

// Chapter 1 has three cards on sec-1: one due now, one new, one not due yet
// (absent from the review queue — the backend only returns due/new cards).
// Chapter 2 (sec-2) starts with zero cards, rendering as the dashed
// "Generate cards" affordance. Chapter 3 (sec-3) has one user-added card,
// not due. A null-label chapter (front matter) must never render.
const cardA = makeCard({ id: "card-a", section_id: "sec-1", front_md: "What is a mitochondria?" });
const cardB = makeCard({ id: "card-b", section_id: "sec-1", front_md: "Define ATP." });
const cardC = makeCard({ id: "card-c", section_id: "sec-1", front_md: "What is the Krebs cycle?" });
const cardD = makeCard({
  id: "card-d",
  section_id: "sec-3",
  front_md: "Why take breaks?",
  origin: "user",
});

const chapter1 = makeChapter({ chapter_label: "Cell Biology Basics", section_ids: ["sec-1"] });
const chapter2 = makeChapter({ chapter_label: "Reading Efficiently", section_ids: ["sec-2"] });
const chapter3 = makeChapter({ chapter_label: "Study Habits", section_ids: ["sec-3"] });
const frontMatter = makeChapter({ chapter_label: null, section_ids: ["sec-0"] });

let sec2Cards: CardOut[];

function setUpHappyPathMocks() {
  mockedListCourses.mockResolvedValue(ok([makeCourse()]));
  mockedListChapters.mockResolvedValue(ok([frontMatter, chapter1, chapter2, chapter3]));
  sec2Cards = [];
  mockedListCards.mockImplementation((sectionId: string) => {
    if (sectionId === "sec-1") return Promise.resolve(ok([cardA, cardB, cardC]));
    if (sectionId === "sec-2") return Promise.resolve(ok(sec2Cards));
    if (sectionId === "sec-3") return Promise.resolve(ok([cardD]));
    return Promise.resolve(ok([]));
  });
  mockedGetReviewQueue.mockResolvedValue(
    ok({
      cards: [
        makeQueueCard({
          id: "card-a",
          section_id: "sec-1",
          due_at: "2026-01-01T00:00:00Z",
          is_new: false,
          interval_days: 1.0,
          reps: 1,
        }),
        makeQueueCard({ id: "card-b", section_id: "sec-1", due_at: null, is_new: true }),
      ],
      due: 1,
      new: 1,
      total: 4,
    }),
  );
  mockedGetReviewSummary.mockResolvedValue(
    ok(makeSummary({ courses: [{ course_id: "course-1", title: "Course One", due_count: 1, new_count: 1 }] })),
  );
  mockedFindActiveCardsJob.mockResolvedValue(null);
}

describe("FlashcardsClient", () => {
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

  it("renders header stats, the deck grid, and the default browsed chapter's table", async () => {
    setUpHappyPathMocks();
    render(<FlashcardsClient />);

    expect(await screen.findByRole("heading", { name: "Flashcards", level: 1 })).toBeInTheDocument();
    expect(await screen.findByText("1 due now · 4 cards total")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /review all due \(1\)/i })).toHaveAttribute(
      "href",
      "/review?course=course-1&start=due",
    );

    // Front matter (null chapter_label) never renders.
    expect(screen.queryByText(/front matter/i)).not.toBeInTheDocument();

    // Chapter 1: has cards, shows real due/card-count badges.
    expect(screen.getByText("Cell Biology Basics")).toBeInTheDocument();
    expect(screen.getByText("1 due")).toBeInTheDocument();
    expect(screen.getByText("3 cards")).toBeInTheDocument();

    // Chapter 2: zero cards renders the dashed generate affordance, not a
    // fabricated retention bar or cost estimate (no estimate endpoint exists
    // for card generation).
    expect(screen.getByText("Reading Efficiently")).toBeInTheDocument();
    expect(
      screen.getByText(/no cards yet — generate a set from this chapter's key ideas/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/\$/)).not.toBeInTheDocument();

    // Default browsed chapter is the first with cards (Chapter 1).
    const table = await screen.findByRole("table");
    expect(within(table).getByText("What is a mitochondria?")).toBeInTheDocument();
    // card-a: due now (strict — has a past due_at, not new) -> accent badge.
    const rowA = within(table).getByText("What is a mitochondria?").closest("tr")!;
    expect(within(rowA).getByText("Due now")).toBeInTheDocument();
    expect(within(rowA).getByText("Generated")).toBeInTheDocument();
    // card-b: new (in the queue, is_new) -> "New", not "Due now".
    const rowB = within(table).getByText("Define ATP.").closest("tr")!;
    expect(within(rowB).getByText("New")).toBeInTheDocument();
    // card-c: absent from the queue entirely (future due_at) -> "Not due yet".
    const rowC = within(table).getByText("What is the Krebs cycle?").closest("tr")!;
    expect(within(rowC).getByText("Not due yet")).toBeInTheDocument();
  });

  it("clicking Browse on another chapter swaps the table", async () => {
    setUpHappyPathMocks();
    const user = userEvent.setup();
    render(<FlashcardsClient />);

    await screen.findByText("What is a mitochondria?"); // default: chapter 1's table

    const chapter3Card = screen.getByText("Study Habits").closest("div")!;
    await user.click(within(chapter3Card).getByRole("button", { name: /browse/i }));

    expect(await screen.findByText("Why take breaks?")).toBeInTheDocument();
    expect(screen.queryByText("What is a mitochondria?")).not.toBeInTheDocument();
    // card-d is a user-added card not present in the review queue at all.
    const row = screen.getByText("Why take breaks?").closest("tr")!;
    expect(within(row).getByText("User-added")).toBeInTheDocument();
    expect(within(row).getByText("Not due yet")).toBeInTheDocument();
  });

  it("generating cards for an empty chapter runs the job and the chapter gains cards on settle", async () => {
    setUpHappyPathMocks();
    mockedGenerateCards.mockResolvedValue(ok({ job_id: "job-1" }, 202));
    const user = userEvent.setup();
    render(<FlashcardsClient />);

    const generateButton = await screen.findByRole("button", { name: /generate cards/i });
    await user.click(generateButton);
    expect(mockedGenerateCards).toHaveBeenCalledWith("sec-2");

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(screen.getByRole("status")).toBeInTheDocument();

    // Simulate the backend now having the generated card before the
    // settle-triggered refetch runs.
    sec2Cards = [makeCard({ id: "card-e", section_id: "sec-2", front_md: "New card" })];

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "succeeded",
        progress: { stage: "done", pct: 100, message: "done" },
      });
    });

    await waitFor(() => {
      const chapter2Card = screen.getByText("Reading Efficiently").closest("div")!;
      expect(within(chapter2Card).getByText("1 card")).toBeInTheDocument();
    });
    expect(screen.queryByRole("button", { name: /generate cards/i })).not.toBeInTheDocument();
  });

  it("shows the job's error text and a working retry when generation fails", async () => {
    setUpHappyPathMocks();
    mockedGenerateCards
      .mockResolvedValueOnce(ok({ job_id: "job-1" }, 202))
      .mockResolvedValueOnce(ok({ job_id: "job-2" }, 202));
    mockedGetJob.mockResolvedValue(
      ok(makeJob({ id: "job-1", status: "failed", error: "ANTHROPIC_API_KEY is not configured" })),
    );

    const user = userEvent.setup();
    render(<FlashcardsClient />);

    await user.click(await screen.findByRole("button", { name: /generate cards/i }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit("update", { id: "job-1", status: "failed", progress: null });
    });

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/generation failed: anthropic_api_key is not configured/i);

    await user.click(within(banner).getByRole("button", { name: /retry/i }));
    expect(mockedGenerateCards).toHaveBeenCalledTimes(2);
  });

  it("switching the course selector refetches that course's chapters and cards", async () => {
    const courseTwo = makeCourse({ id: "course-2", title: "Course Two" });
    mockedListCourses.mockResolvedValue(ok([makeCourse(), courseTwo]));
    mockedListChapters.mockImplementation((courseId: string) => {
      if (courseId === "course-1") return Promise.resolve(ok([chapter1]));
      return Promise.resolve(
        ok([makeChapter({ chapter_label: "Intro to Course Two", section_ids: ["sec-9"] })]),
      );
    });
    mockedListCards.mockImplementation((sectionId: string) => {
      if (sectionId === "sec-1") return Promise.resolve(ok([cardA]));
      if (sectionId === "sec-9") return Promise.resolve(ok([]));
      return Promise.resolve(ok([]));
    });
    mockedGetReviewQueue.mockResolvedValue(ok({ cards: [], due: 0, new: 0, total: 0 }));
    mockedGetReviewSummary.mockResolvedValue(ok(makeSummary()));

    const user = userEvent.setup();
    render(<FlashcardsClient />);

    expect(await screen.findByText("Cell Biology Basics")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Course Two" }));

    expect(await screen.findByText("Intro to Course Two")).toBeInTheDocument();
    expect(screen.queryByText("Cell Biology Basics")).not.toBeInTheDocument();
    expect(mockedListChapters).toHaveBeenCalledWith("course-2");
  });

  it("shows an error banner with a working retry when courses fail to load", async () => {
    mockedListCourses.mockResolvedValueOnce(err(500)).mockResolvedValueOnce(ok([makeCourse()]));
    mockedListChapters.mockResolvedValue(ok([chapter1]));
    mockedListCards.mockResolvedValue(ok([cardA]));
    mockedGetReviewQueue.mockResolvedValue(ok({ cards: [], due: 0, new: 0, total: 1 }));
    mockedGetReviewSummary.mockResolvedValue(ok(makeSummary()));

    const user = userEvent.setup();
    render(<FlashcardsClient />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/loading courses failed/i);

    await user.click(within(banner).getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("Cell Biology Basics")).toBeInTheDocument();
  });

  it("shows an empty state linking home when there are no ready courses", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse({ status: "draft" })]));
    mockedGetReviewSummary.mockResolvedValue(ok(makeSummary()));

    render(<FlashcardsClient />);

    expect(await screen.findByText(/no courses yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /go to home/i })).toHaveAttribute("href", "/");
    expect(mockedListChapters).not.toHaveBeenCalled();
  });

  it("shows an error banner with a working retry when chapter/card data fails to load", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse()]));
    mockedListChapters.mockResolvedValueOnce(err(500)).mockResolvedValueOnce(ok([chapter1]));
    mockedListCards.mockResolvedValue(ok([cardA]));
    mockedGetReviewQueue.mockResolvedValue(ok({ cards: [], due: 0, new: 0, total: 1 }));
    mockedGetReviewSummary.mockResolvedValue(ok(makeSummary()));

    const user = userEvent.setup();
    render(<FlashcardsClient />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/loading chapters failed/i);

    await user.click(within(banner).getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("Cell Biology Basics")).toBeInTheDocument();
  });
});
