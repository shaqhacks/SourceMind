import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import FlashcardsClient from "@/components/flashcards/FlashcardsClient";
import {
  findActiveCardsJob,
  generateCards,
  getJob,
  getReviewQueue,
  getReviewSelection,
  getReviewSummary,
  listCards,
  listChapters,
  listCourses,
  type ApiResult,
  type CardOut,
  type ChapterOut,
  type CourseOut,
  type JobOut,
  type ReviewQueueCardOut,
  type ReviewQueueOut,
  type ReviewSelectionOut,
  type ReviewSummaryOut,
} from "@/lib/api/client";
import { gradeCardAndNotify } from "@/lib/review/gradeCardAndNotify";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

import { err, ok } from "./support/api-result";
import { FakeEventSource } from "./support/fake-event-source";

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  MAX_QUEUE_FETCH: 200,
  listCourses: vi.fn(),
  listChapters: vi.fn(),
  listCards: vi.fn(),
  getReviewQueue: vi.fn(),
  getReviewSelection: vi.fn(),
  getReviewSummary: vi.fn(),
  generateCards: vi.fn(),
  findActiveCardsJob: vi.fn(),
  getJob: vi.fn(),
}));

vi.mock("@/lib/review/gradeCardAndNotify", () => ({
  gradeCardAndNotify: vi.fn(),
}));

const mockedListCourses = vi.mocked(listCourses);
const mockedListChapters = vi.mocked(listChapters);
const mockedListCards = vi.mocked(listCards);
const mockedGetReviewQueue = vi.mocked(getReviewQueue);
const mockedGetReviewSummary = vi.mocked(getReviewSummary);
const mockedGenerateCards = vi.mocked(generateCards);
const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);
const mockedGetJob = vi.mocked(getJob);
const mockedGetReviewSelection = vi.mocked(getReviewSelection);
const mockedGradeCardAndNotify = vi.mocked(gradeCardAndNotify);

function makeCourse(overrides: Partial<CourseOut> = {}): CourseOut {
  return {
    id: "course-1",
    title: "Course One",
    status: "ready",
    section_count: 3,
    failed_asset_count: 0,
    is_sample: false,
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
    chapter_label: "Chapter 1",
    section_title: "Section 1",
    is_due: false,
    last_grade: null,
    ...overrides,
  };
}

function makeQueue(overrides: Partial<ReviewQueueOut> = {}): ReviewQueueOut {
  const cards = overrides.cards ?? [];
  const total = overrides.total ?? cards.length;
  const due = overrides.due ?? 0;
  const newCount = overrides.new ?? Math.max(total - due, 0);
  return {
    cards,
    due,
    new: newCount,
    total,
    overdue_count: due,
    new_count: newCount,
    available_count: due + newCount,
    total_count: total,
    ...overrides,
  };
}

function makeSelection(overrides: Partial<ReviewSelectionOut> = {}): ReviewSelectionOut {
  return {
    cards: [],
    missing_card_ids: [],
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
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
    error_detail: null,
    retryable: true,
    attempts: 0,
    cancel_requested_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

// Chapter 1 has three cards on sec-1: one due now, one new, one not due yet.
// Chapter 2 (sec-2) starts with zero cards, rendering as the dashed
// "Generate cards" affordance. Chapter 3 (sec-3) has one user-added card,
// needing attention. A null-label chapter (front matter) must never render.
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
    ok(makeQueue({
      cards: [
        makeQueueCard({
          id: "card-a",
          section_id: "sec-1",
          due_at: "2026-01-01T00:00:00Z",
          is_new: false,
          is_due: true,
          interval_days: 1.0,
          reps: 1,
        }),
        makeQueueCard({ id: "card-b", section_id: "sec-1", due_at: null, is_new: true }),
        makeQueueCard({
          id: "card-c",
          section_id: "sec-1",
          front_md: "What is the Krebs cycle?",
          back_md: "A series of reactions that releases stored energy.",
          due_at: "2026-03-01T00:00:00Z",
          is_new: false,
          is_due: false,
          interval_days: 8,
          reps: 2,
          last_grade: 3,
        }),
        makeQueueCard({
          id: "card-d",
          section_id: "sec-3",
          front_md: "Why take breaks?",
          back_md: "Breaks reduce fatigue and improve recall.",
          due_at: "2026-03-01T00:00:00Z",
          is_new: false,
          is_due: false,
          interval_days: 4,
          reps: 1,
          chapter_label: "Study Habits",
          last_grade: 1,
        }),
      ],
      due: 1,
      new: 1,
      total: 4,
      overdue_count: 1,
      new_count: 1,
      available_count: 2,
      total_count: 4,
    })),
  );
  mockedGetReviewSelection.mockResolvedValue(
    ok(
      makeSelection({
        cards: [
          makeQueueCard({
            id: "card-a",
            section_id: "sec-1",
            due_at: "2026-01-01T00:00:00Z",
            is_new: false,
            is_due: true,
            interval_days: 1.0,
            reps: 1,
          }),
          makeQueueCard({ id: "card-b", section_id: "sec-1", due_at: null, is_new: true }),
          makeQueueCard({
            id: "card-c",
            section_id: "sec-1",
            front_md: "What is the Krebs cycle?",
            back_md: "A series of reactions that releases stored energy.",
            due_at: "2026-03-01T00:00:00Z",
            is_new: false,
            is_due: false,
            interval_days: 8,
            reps: 2,
            last_grade: 3,
          }),
          makeQueueCard({
            id: "card-d",
            section_id: "sec-3",
            front_md: "Why take breaks?",
            back_md: "Breaks reduce fatigue and improve recall.",
            due_at: "2026-03-01T00:00:00Z",
            is_new: false,
            is_due: false,
            interval_days: 4,
            reps: 1,
            chapter_label: "Study Habits",
            last_grade: 1,
          }),
        ],
      }),
    ),
  );
  mockedGetReviewSummary.mockResolvedValue(
    ok(
      makeSummary({
        courses: [
          {
            course_id: "course-1",
            title: "Course One",
            due_count: 1,
            overdue_count: 1,
            new_count: 1,
            available_count: 2,
            total_count: 4,
            needs_attention_count: 1,
          },
        ],
      }),
    ),
  );
  mockedFindActiveCardsJob.mockResolvedValue(null);
  mockedGradeCardAndNotify.mockImplementation(async () => {
    notifyReviewSettled();
    return ok({ next_due_at: "2026-08-10T00:00:00Z", remaining_due: 0 });
  });
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
    expect(await screen.findByText("4 total · 1 due · 1 new · 1 needs attention")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /review due/i })).toHaveAttribute(
      "href",
      "/review?course=course-1&scope=available&start=due",
    );
    expect(screen.getByRole("link", { name: /review all/i })).toHaveAttribute(
      "href",
      "/review?course=course-1&scope=all",
    );
    expect(screen.getByRole("link", { name: /needs attention/i })).toHaveAttribute(
      "href",
      "/review?course=course-1&scope=needs_attention",
    );
    expect(mockedGetReviewSummary).toHaveBeenCalledTimes(1);
    expect(mockedGetReviewSelection).toHaveBeenCalledWith("course-1", [
      "card-a",
      "card-b",
      "card-c",
      "card-d",
    ]);
    expect(mockedGetReviewQueue).not.toHaveBeenCalled();

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
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const list = await screen.findByRole("list", { name: /all cards — cell biology basics/i });
    expect(within(list).getByText("What is a mitochondria?")).toBeInTheDocument();
    // card-a: due now (strict — has a past due_at, not new) -> accent badge.
    const itemA = within(list).getByText("What is a mitochondria?").closest("li")!;
    expect(within(itemA).getByText("Due now")).toBeInTheDocument();
    expect(within(itemA).getByText("Generated")).toBeInTheDocument();
    // card-b: new (in the queue, is_new) -> "New", not "Due now".
    const itemB = within(list).getByText("Define ATP.").closest("li")!;
    expect(within(itemB).getByText("New")).toBeInTheDocument();
    // card-c: in the all-card queue but is_due=false -> "Not due yet".
    const itemC = within(list).getByText("What is the Krebs cycle?").closest("li")!;
    expect(within(itemC).getByText("Not due yet")).toBeInTheDocument();
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
    // card-d is user-added and currently marked Again in the exact selection metadata.
    const item = screen.getByText("Why take breaks?").closest("li")!;
    expect(within(item).getByText("User-added")).toBeInTheDocument();
    expect(within(item).getByText("Not due yet")).toBeInTheDocument();
    expect(within(item).getByText("Needs attention")).toBeInTheDocument();
  });

  it("uses exact summary counts and batches visible-card metadata beyond 200 cards", async () => {
    const manyCards = Array.from({ length: 201 }, (_, index) =>
      makeCard({
        id: `card-${index + 1}`,
        section_id: "sec-1",
        front_md: index === 200 ? "Outside cap" : `Card ${index + 1}`,
      }),
    );
    mockedListCourses.mockResolvedValue(ok([makeCourse()]));
    mockedListChapters.mockResolvedValue(ok([chapter1]));
    mockedListCards.mockResolvedValue(ok(manyCards));
    mockedGetReviewSummary.mockResolvedValue(
      ok(
        makeSummary({
          courses: [
            {
              course_id: "course-1",
              title: "Course One",
              due_count: 1,
              overdue_count: 1,
              new_count: 200,
              available_count: 201,
              total_count: 201,
              needs_attention_count: 1,
            },
          ],
        }),
      ),
    );
    mockedGetReviewQueue.mockResolvedValue(
      ok(
        makeQueue({
          cards: manyCards.slice(0, 200).map((card) =>
            makeQueueCard({
              id: card.id,
              front_md: card.front_md,
              back_md: card.back_md,
              is_new: true,
            }),
          ),
          total_count: 201,
        }),
      ),
    );
    mockedGetReviewSelection.mockImplementation((_courseId, cardIds) =>
      Promise.resolve(
        ok(
          makeSelection({
            cards: cardIds.map((id) =>
              makeQueueCard({
                id,
                front_md: id === "card-201" ? "Outside cap" : id,
                back_md: id === "card-201" ? "Outside cap answer" : `${id} answer`,
                is_new: id !== "card-201",
                is_due: id === "card-201",
                last_grade: id === "card-201" ? 1 : null,
              }),
            ),
          }),
        ),
      ),
    );

    const user = userEvent.setup();
    render(<FlashcardsClient />);

    expect(await screen.findByText("201 total · 1 due · 200 new · 1 needs attention")).toBeInTheDocument();
    expect(mockedGetReviewQueue).not.toHaveBeenCalled();
    await waitFor(() => expect(mockedGetReviewSelection).toHaveBeenCalledTimes(2));
    expect(mockedGetReviewSelection.mock.calls[0][1]).toHaveLength(200);
    expect(mockedGetReviewSelection.mock.calls[1][1]).toEqual(["card-201"]);
    for (const [, cardIds] of mockedGetReviewSelection.mock.calls) {
      expect(cardIds.length).toBeLessThanOrEqual(200);
    }

    const item = screen.getByText("Outside cap").closest("li")!;
    expect(within(item).getByText("Due now")).toBeInTheDocument();
    expect(within(item).getByText("Needs attention")).toBeInTheDocument();

    await user.click(within(item).getByRole("button", { name: /show answer/i }));

    expect(within(item).getByRole("group", { name: /grade flashcard/i })).toBeInTheDocument();
  });

  it("refreshes summary and visible metadata after inline grading", async () => {
    setUpHappyPathMocks();
    mockedGetReviewSummary
      .mockResolvedValueOnce(
        ok(
          makeSummary({
            courses: [
              {
                course_id: "course-1",
                title: "Course One",
                due_count: 1,
                overdue_count: 1,
                new_count: 1,
                available_count: 2,
                total_count: 4,
                needs_attention_count: 1,
              },
            ],
          }),
        ),
      )
      .mockResolvedValue(
        ok(
          makeSummary({
            courses: [
              {
                course_id: "course-1",
                title: "Course One",
                due_count: 0,
                overdue_count: 0,
                new_count: 1,
                available_count: 1,
                total_count: 4,
                needs_attention_count: 0,
              },
            ],
          }),
        ),
      );
    mockedGetReviewSelection
      .mockResolvedValueOnce(
        ok(
          makeSelection({
            cards: [
              makeQueueCard({
                id: "card-a",
                section_id: "sec-1",
                is_new: false,
                is_due: true,
              }),
              makeQueueCard({ id: "card-b", section_id: "sec-1", is_new: true }),
              makeQueueCard({
                id: "card-c",
                section_id: "sec-1",
                front_md: "What is the Krebs cycle?",
                is_new: false,
                is_due: false,
                last_grade: 3,
              }),
              makeQueueCard({
                id: "card-d",
                section_id: "sec-3",
                front_md: "Why take breaks?",
                back_md: "Breaks reduce fatigue and improve recall.",
                is_new: false,
                is_due: true,
                chapter_label: "Study Habits",
                last_grade: 1,
              }),
            ],
          }),
        ),
      )
      .mockResolvedValue(
        ok(
          makeSelection({
            cards: [
              makeQueueCard({
                id: "card-a",
                section_id: "sec-1",
                is_new: false,
                is_due: false,
                last_grade: 3,
              }),
              makeQueueCard({ id: "card-b", section_id: "sec-1", is_new: true }),
              makeQueueCard({
                id: "card-c",
                section_id: "sec-1",
                front_md: "What is the Krebs cycle?",
                is_new: false,
                is_due: false,
                last_grade: 3,
              }),
              makeQueueCard({
                id: "card-d",
                section_id: "sec-3",
                front_md: "Why take breaks?",
                back_md: "Breaks reduce fatigue and improve recall.",
                is_new: false,
                is_due: false,
                chapter_label: "Study Habits",
                last_grade: 3,
              }),
            ],
          }),
        ),
      );
    const user = userEvent.setup();
    render(<FlashcardsClient />);

    await screen.findByText("4 total · 1 due · 1 new · 1 needs attention");
    const chapter3Card = screen.getByText("Study Habits").closest("div")!;
    await user.click(within(chapter3Card).getByRole("button", { name: /browse/i }));
    const item = await screen.findByText("Why take breaks?").then((node) => node.closest("li")!);
    expect(within(item).getByText("Needs attention")).toBeInTheDocument();

    await user.click(within(item).getByRole("button", { name: /show answer/i }));
    await user.click(within(item).getByRole("button", { name: /good/i }));

    expect(await screen.findByText("4 total · 0 due · 1 new · 0 needs attention")).toBeInTheDocument();
    await waitFor(() => expect(mockedGetReviewSelection).toHaveBeenCalledTimes(2));
    const refreshedItem = screen.getByText("Why take breaks?").closest("li")!;
    expect(within(refreshedItem).queryByText("Needs attention")).not.toBeInTheDocument();
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
    mockedGetReviewQueue.mockResolvedValue(ok(makeQueue()));
    mockedGetReviewSummary.mockResolvedValue(ok(makeSummary()));

    const user = userEvent.setup();
    render(<FlashcardsClient />);

    expect(await screen.findByText("Cell Biology Basics")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Course Two" }));

    expect(await screen.findByText("Intro to Course Two")).toBeInTheDocument();
    expect(screen.queryByText("Cell Biology Basics")).not.toBeInTheDocument();
    expect(mockedListChapters).toHaveBeenCalledWith("course-2");
  });

  it("ignores stale prior-course summary and metadata responses after a course switch", async () => {
    const courseTwo = makeCourse({ id: "course-2", title: "Course Two" });
    const courseOneChapters = deferred<ApiResult<ChapterOut[]>>();
    mockedListCourses.mockResolvedValue(ok([makeCourse(), courseTwo]));
    mockedListChapters.mockImplementation((courseId: string) => {
      if (courseId === "course-1") return courseOneChapters.promise;
      return Promise.resolve(
        ok([makeChapter({ chapter_label: "Course Two Chapter", section_ids: ["sec-9"] })]),
      );
    });
    mockedListCards.mockImplementation((sectionId: string) => {
      if (sectionId === "sec-1") return Promise.resolve(ok([cardA]));
      if (sectionId === "sec-9") {
        return Promise.resolve(
          ok([makeCard({ id: "card-9", section_id: "sec-9", front_md: "Course Two card" })]),
        );
      }
      return Promise.resolve(ok([]));
    });
    mockedGetReviewSummary.mockResolvedValue(
      ok(
        makeSummary({
          courses: [
            {
              course_id: "course-1",
              title: "Course One",
              due_count: 1,
              overdue_count: 1,
              new_count: 0,
              available_count: 1,
              total_count: 1,
              needs_attention_count: 1,
            },
            {
              course_id: "course-2",
              title: "Course Two",
              due_count: 0,
              overdue_count: 0,
              new_count: 1,
              available_count: 1,
              total_count: 1,
              needs_attention_count: 0,
            },
          ],
        }),
      ),
    );
    mockedGetReviewSelection.mockImplementation((courseId, cardIds) =>
      Promise.resolve(
        ok(
          makeSelection({
            cards: cardIds.map((id) =>
              makeQueueCard({
                id,
                section_id: courseId === "course-2" ? "sec-9" : "sec-1",
                front_md: courseId === "course-2" ? "Course Two card" : "Course One stale card",
                is_new: courseId === "course-2",
                is_due: courseId === "course-1",
                last_grade: courseId === "course-1" ? 1 : null,
              }),
            ),
          }),
        ),
      ),
    );

    const user = userEvent.setup();
    render(<FlashcardsClient />);

    await user.click(await screen.findByRole("tab", { name: "Course Two" }));

    expect(await screen.findByText("Course Two Chapter")).toBeInTheDocument();
    expect(await screen.findByText("1 total · 0 due · 1 new · 0 needs attention")).toBeInTheDocument();

    courseOneChapters.resolve(ok([chapter1]));

    await waitFor(() => expect(screen.getByText("Course Two Chapter")).toBeInTheDocument());
    expect(screen.queryByText("Cell Biology Basics")).not.toBeInTheDocument();
    expect(screen.queryByText("Course One stale card")).not.toBeInTheDocument();
    expect(screen.getByText("1 total · 0 due · 1 new · 0 needs attention")).toBeInTheDocument();
  });

  it("shows an error banner with a working retry when courses fail to load", async () => {
    mockedListCourses.mockResolvedValueOnce(err(500)).mockResolvedValueOnce(ok([makeCourse()]));
    mockedListChapters.mockResolvedValue(ok([chapter1]));
    mockedListCards.mockResolvedValue(ok([cardA]));
    mockedGetReviewQueue.mockResolvedValue(ok(makeQueue({ total: 1 })));
    mockedGetReviewSummary.mockResolvedValue(ok(makeSummary()));

    const user = userEvent.setup();
    render(<FlashcardsClient />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/loading courses failed/i);

    await user.click(within(banner).getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("Cell Biology Basics")).toBeInTheDocument();
  });

  it("shows an error banner with a working retry when review metadata fails to load", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse()]));
    mockedListChapters.mockResolvedValue(ok([chapter1]));
    mockedListCards.mockResolvedValue(ok([cardA]));
    mockedGetReviewSelection
      .mockResolvedValueOnce(err(500))
      .mockResolvedValueOnce(ok(makeSelection({ cards: [makeQueueCard({ id: "card-a" })] })));
    mockedGetReviewSummary.mockResolvedValue(
      ok(
        makeSummary({
          courses: [
            {
              course_id: "course-1",
              title: "Course One",
              due_count: 0,
              overdue_count: 0,
              new_count: 1,
              available_count: 1,
              total_count: 1,
              needs_attention_count: 0,
            },
          ],
        }),
      ),
    );

    const user = userEvent.setup();
    render(<FlashcardsClient />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/loading review metadata failed/i);

    await user.click(within(banner).getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("Cell Biology Basics")).toBeInTheDocument();
  });

  it("shows an error banner with a working retry when flashcards fail to load", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse()]));
    mockedListChapters.mockResolvedValue(ok([chapter1]));
    mockedListCards.mockResolvedValueOnce(err(500)).mockResolvedValueOnce(ok([cardA]));
    mockedGetReviewQueue.mockResolvedValue(ok(makeQueue({ total: 1 })));
    mockedGetReviewSummary.mockResolvedValue(ok(makeSummary()));

    const user = userEvent.setup();
    render(<FlashcardsClient />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/loading flashcards failed/i);

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
    mockedGetReviewQueue.mockResolvedValue(ok(makeQueue({ total: 1 })));
    mockedGetReviewSummary.mockResolvedValue(ok(makeSummary()));

    const user = userEvent.setup();
    render(<FlashcardsClient />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/loading chapters failed/i);

    await user.click(within(banner).getByRole("button", { name: /retry/i }));

    expect(await screen.findByText("Cell Biology Basics")).toBeInTheDocument();
  });
});
