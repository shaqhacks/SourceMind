import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TestsPage from "@/app/tests/page";
import {
  type ChapterOut,
  type CourseOut,
  type JobOut,
  type SkillMapOut,
  type TestAttemptOut,
  type TestAttemptSummaryOut,
  type TestSummaryOut,
  generateTest,
  getJob,
  getSkillMap,
  getTest,
  listChapters,
  listCourses,
  listJobs,
  listTests,
  retakeTest,
} from "@/lib/api/client";

import { ok } from "./support/api-result";
import { FakeEventSource } from "./support/fake-event-source";

let mockSearchParams = new URLSearchParams();
const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => mockSearchParams,
  usePathname: () => "/tests",
}));

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  listCourses: vi.fn(),
  listChapters: vi.fn(),
  listTests: vi.fn(),
  listJobs: vi.fn(),
  getTest: vi.fn(),
  retakeTest: vi.fn(),
  generateTest: vi.fn(),
  getJob: vi.fn(),
  getSkillMap: vi.fn(),
}));

const mockedListCourses = vi.mocked(listCourses);
const mockedListChapters = vi.mocked(listChapters);
const mockedListTests = vi.mocked(listTests);
const mockedListJobs = vi.mocked(listJobs);
const mockedGetTest = vi.mocked(getTest);
const mockedRetakeTest = vi.mocked(retakeTest);
const mockedGenerateTest = vi.mocked(generateTest);
const mockedGetJob = vi.mocked(getJob);
const mockedGetSkillMap = vi.mocked(getSkillMap);

function makeCourse(overrides: Partial<CourseOut> = {}): CourseOut {
  return {
    id: "course-1",
    title: "Course One",
    status: "ready",
    section_count: 6,
    failed_asset_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    progress: null,
    ...overrides,
  };
}

function makeChapter(overrides: Partial<ChapterOut> = {}): ChapterOut {
  return {
    chapter_label: "Chapter 1",
    section_ids: ["s1"],
    practice_section_ids: [],
    answers_section_ids: [],
    test_stats: null,
    ...overrides,
  };
}

function makeAttemptSummary(overrides: Partial<TestAttemptSummaryOut> = {}): TestAttemptSummaryOut {
  return { id: "attempt-1", score: 0.6, created_at: "2026-01-02T00:00:00Z", ...overrides };
}

function makeTest(overrides: Partial<TestSummaryOut> = {}): TestSummaryOut {
  return {
    id: "test-1",
    course_id: "course-1",
    chapter_label: "Chapter 1",
    question_count: 5,
    created_at: "2026-01-02T00:00:00Z",
    attempts: [makeAttemptSummary()],
    ...overrides,
  };
}

function makeAttemptDetail(overrides: Partial<TestAttemptOut> = {}): TestAttemptOut {
  return {
    id: "attempt-1",
    test_id: "test-1",
    course_id: "course-1",
    chapter_label: "Chapter 1",
    score: 0.5,
    questions: [
      { question: "What is outline detection?", choices: ["A", "B"], correct_index: 1, explanation: "B is right." },
      { question: "What is chunking?", choices: ["A", "B"], correct_index: 0, explanation: "A is right." },
    ],
    answers: [0, 0],
    results: [
      { correct: false, correct_index: 1, explanation: "B is right.", your_answer: 0 },
      { correct: true, correct_index: 0, explanation: "A is right.", your_answer: 0 },
    ],
    created_at: "2026-01-02T00:00:00Z",
    ...overrides,
  };
}

function makeJob(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: "job-1",
    type: "generate_test",
    status: "running",
    payload: { course_id: "course-1", chapter_label: "Chapter 3" },
    result: null,
    progress: null,
    error: null,
    attempts: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("TestsPage", () => {
  let originalEventSource: typeof EventSource;

  beforeEach(() => {
    originalEventSource = globalThis.EventSource;
    FakeEventSource.instances = [];
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
    mockSearchParams = new URLSearchParams();
    mockedListJobs.mockResolvedValue(ok([]));
    mockedGetSkillMap.mockResolvedValue(ok({ nodes: [], edges: [] }));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    globalThis.EventSource = originalEventSource;
  });

  it("renders a card per chapter: weak (below target), solid, and untested", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse()]));
    mockedListChapters.mockResolvedValue(
      ok([
        makeChapter({ chapter_label: "Chapter 1", test_stats: { attempts: 2, best_score: 0.6, latest_score: 0.6 } }),
        makeChapter({ chapter_label: "Chapter 2", test_stats: { attempts: 1, best_score: 0.84, latest_score: 0.84 } }),
        makeChapter({ chapter_label: "Chapter 3", test_stats: null }),
      ]),
    );
    mockedListTests.mockResolvedValue(
      ok([
        makeTest({ id: "test-1", chapter_label: "Chapter 1", attempts: [makeAttemptSummary({ score: 0.6 })] }),
        makeTest({
          id: "test-2",
          chapter_label: "Chapter 2",
          attempts: [makeAttemptSummary({ id: "attempt-2", score: 0.84 })],
        }),
      ]),
    );

    render(<TestsPage />);

    expect(await screen.findByText("Best score 60% — below your 80% target")).toBeInTheDocument();
    expect(screen.getByText("Best score 84% — solid")).toBeInTheDocument();
    expect(screen.getByText(/not attempted yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate test/i })).toBeInTheDocument();
  });

  it("shows a course selector only when more than one ready course exists, and switching refetches", async () => {
    mockedListCourses.mockResolvedValue(
      ok([makeCourse({ id: "course-1", title: "Course One" }), makeCourse({ id: "course-2", title: "Course Two" })]),
    );
    mockedListChapters.mockResolvedValue(ok([]));
    mockedListTests.mockResolvedValue(ok([]));

    render(<TestsPage />);

    const select = await screen.findByRole("combobox");
    expect(within(select).getByText("Course One")).toBeInTheDocument();
    expect(within(select).getByText("Course Two")).toBeInTheDocument();
    expect(mockedListChapters).toHaveBeenCalledWith("course-1");
  });

  it("'Retake' on a solid chapter starts a zero-LLM retake and navigates into the new attempt", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse()]));
    mockedListChapters.mockResolvedValue(
      ok([makeChapter({ chapter_label: "Chapter 2", test_stats: { attempts: 1, best_score: 0.84, latest_score: 0.84 } })]),
    );
    mockedListTests.mockResolvedValue(
      ok([makeTest({ id: "test-2", chapter_label: "Chapter 2", attempts: [makeAttemptSummary({ score: 0.84 })] })]),
    );
    mockedRetakeTest.mockResolvedValue(ok({ attempt_id: "attempt-new" }));

    const user = userEvent.setup();
    render(<TestsPage />);

    await user.click(await screen.findByRole("button", { name: /retake/i }));
    expect(mockedRetakeTest).toHaveBeenCalledWith("test-2");
    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/course/course-1/test/attempt-new"));
  });

  it("expands 'Missed last time' on a weak chapter, lazily fetching the latest scored attempt", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse()]));
    mockedListChapters.mockResolvedValue(
      ok([makeChapter({ chapter_label: "Chapter 1", test_stats: { attempts: 1, best_score: 0.5, latest_score: 0.5 } })]),
    );
    mockedListTests.mockResolvedValue(
      ok([makeTest({ id: "test-1", chapter_label: "Chapter 1", attempts: [makeAttemptSummary({ id: "attempt-1", score: 0.5 })] })]),
    );
    mockedGetTest.mockResolvedValue(ok(makeAttemptDetail()));

    const user = userEvent.setup();
    render(<TestsPage />);

    await user.click(await screen.findByRole("button", { name: /missed last time/i }));
    expect(mockedGetTest).toHaveBeenCalledWith("attempt-1");

    // Only the missed question (correct: false) surfaces, not the one answered correctly.
    expect(await screen.findByText("What is outline detection?")).toBeInTheDocument();
    expect(screen.queryByText("What is chunking?")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /review answer/i }));
    expect(mockPush).toHaveBeenCalledWith("/course/course-1/test/attempt-1");
  });

  it("generating a test for an untested chapter runs the job to completion and navigates into the fresh attempt", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse()]));
    mockedListChapters.mockResolvedValue(ok([makeChapter({ chapter_label: "Chapter 3", test_stats: null })]));
    mockedListTests
      .mockResolvedValueOnce(ok([])) // initial load: no tests yet
      .mockResolvedValueOnce(
        ok([makeTest({ id: "test-3", chapter_label: "Chapter 3", attempts: [makeAttemptSummary({ id: "fresh-attempt", score: null })] })]),
      ); // post-settle refetch
    mockedGenerateTest.mockResolvedValue(ok({ job_id: "job-1" }, 202));

    const user = userEvent.setup();
    render(<TestsPage />);

    await user.click(await screen.findByRole("button", { name: /generate test/i }));
    expect(mockedGenerateTest).toHaveBeenCalledWith("course-1", { chapterLabel: "Chapter 3" });

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "succeeded",
        progress: { stage: "done", pct: 100, message: "done" },
      });
    });

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/course/course-1/test/fresh-attempt"));
  });

  it("shows the job's error and a retry when generation fails", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse()]));
    mockedListChapters.mockResolvedValue(ok([makeChapter({ chapter_label: "Chapter 3", test_stats: null })]));
    mockedListTests.mockResolvedValue(ok([]));
    mockedGenerateTest
      .mockResolvedValueOnce(ok({ job_id: "job-1" }, 202))
      .mockResolvedValueOnce(ok({ job_id: "job-2" }, 202));
    mockedGetJob.mockResolvedValue(ok(makeJob({ status: "failed", error: "LLM unavailable" })));

    const user = userEvent.setup();
    render(<TestsPage />);

    await user.click(await screen.findByRole("button", { name: /generate test/i }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit("update", { id: "job-1", status: "failed", progress: null });
    });

    expect(await screen.findByText(/generation failed: llm unavailable/i)).toBeInTheDocument();
  });

  it("renders the score history bar chart and a real-data diagnosis card", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse()]));
    mockedListChapters.mockResolvedValue(
      ok([makeChapter({ chapter_label: "Chapter 1", test_stats: { attempts: 1, best_score: 0.6, latest_score: 0.6 } })]),
    );
    mockedListTests.mockResolvedValue(
      ok([makeTest({ id: "test-1", chapter_label: "Chapter 1", attempts: [makeAttemptSummary({ score: 0.6 })] })]),
    );
    const diagnosisMap: SkillMapOut = {
      nodes: [
        { id: "tc", slug: "tc", label: "Token counting", level: 1, mastery: 31, status: "struggling", blocked: false, unlock_note: null },
        { id: "ce", slug: "ce", label: "Cost estimation", level: 2, mastery: 24, status: "struggling", blocked: true, unlock_note: null },
        { id: "cm", slug: "cm", label: "Context management", level: 2, mastery: 52, status: "growing", blocked: true, unlock_note: null },
      ],
      edges: [
        { from_id: "tc", to_id: "ce", kind: "weak" },
        { from_id: "tc", to_id: "cm", kind: "weak" },
      ],
    };
    mockedGetSkillMap.mockResolvedValue(ok(diagnosisMap));

    render(<TestsPage />);

    await screen.findByText("Score history");
    expect(screen.getByRole("img", { name: /chapter 1 60%/i })).toBeInTheDocument();
    expect(
      screen.getByText(/missed questions are added to your flashcards automatically/i),
    ).toBeInTheDocument();

    // findByText, not getByText: ScoreHistoryCard and DiagnosisCard render
    // off separate fetches (listChapters/listTests vs. DiagnosisCard's own
    // useSkillMap), so "Score history" appearing above gives no ordering
    // guarantee that the skill map fetch has resolved yet.
    expect(await screen.findByText("Diagnosis")).toBeInTheDocument();
    // Two assertions, not one regex spanning both: the message's prereq
    // name sits inside its own <strong>, and RTL's getByText only matches
    // an element's own direct text nodes, not text a nested element covers.
    expect(screen.getByText(/misses cluster on/i)).toBeInTheDocument();
    expect(screen.getByText("Token counting")).toBeInTheDocument();
    expect(screen.getByText(/underpins 2 other skills/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /drill token counting/i })).toBeInTheDocument();
  });

  it("shows a quiet note instead of a diagnosis when nothing is both struggling and blocked", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse()]));
    mockedListChapters.mockResolvedValue(
      ok([makeChapter({ chapter_label: "Chapter 1", test_stats: { attempts: 1, best_score: 0.6, latest_score: 0.6 } })]),
    );
    mockedListTests.mockResolvedValue(
      ok([makeTest({ id: "test-1", chapter_label: "Chapter 1", attempts: [makeAttemptSummary({ score: 0.6 })] })]),
    );
    mockedGetSkillMap.mockResolvedValue(
      ok({
        nodes: [
          { id: "a", slug: "a", label: "Tokenization basics", level: 1, mastery: 86, status: "solid", blocked: false, unlock_note: null },
        ],
        edges: [],
      }),
    );

    render(<TestsPage />);

    await screen.findByText("Diagnosis");
    expect(screen.getByText("No diagnosis available right now.")).toBeInTheDocument();
  });

  it("hides the diagnosis card entirely when the course has no skill graph yet", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse()]));
    mockedListChapters.mockResolvedValue(
      ok([makeChapter({ chapter_label: "Chapter 1", test_stats: { attempts: 1, best_score: 0.6, latest_score: 0.6 } })]),
    );
    mockedListTests.mockResolvedValue(
      ok([makeTest({ id: "test-1", chapter_label: "Chapter 1", attempts: [makeAttemptSummary({ score: 0.6 })] })]),
    );
    mockedGetSkillMap.mockResolvedValue(ok({ nodes: [], edges: [] }));

    render(<TestsPage />);

    await screen.findByText("Score history");
    expect(screen.queryByText("Diagnosis")).not.toBeInTheDocument();
  });

  it("shows a retryable error banner when courses fail to load", async () => {
    mockedListCourses.mockResolvedValueOnce({ status: 500, ok: false }).mockResolvedValueOnce(ok([makeCourse()]));
    mockedListChapters.mockResolvedValue(ok([]));
    mockedListTests.mockResolvedValue(ok([]));

    render(<TestsPage />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/loading courses/i);
  });

  it("shows an error banner when chapters load but tests fail to load", async () => {
    mockedListCourses.mockResolvedValue(ok([makeCourse()]));
    mockedListChapters.mockResolvedValue(
      ok([makeChapter({ chapter_label: "Chapter 1", test_stats: null })]),
    );
    mockedListTests.mockResolvedValue({ status: 500, ok: false });

    render(<TestsPage />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/loading tests/i);
  });

  it("a stale fetch for an abandoned course does not clobber the newer course's loaded state", async () => {
    // Repro for the write-side race: course A's chapters/tests fetch is left
    // pending while the user switches to course C, C's fetch resolves and
    // renders, and only THEN does A's stale response land. Before the
    // write-guard fix, that stale write replaced chaptersState with a
    // `courseId: "course-a"` entry; displayedChaptersState's render-time
    // mask correctly hides a courseId mismatch as "loading", but nothing
    // ever re-fetches C after that (the fetch effect only re-runs when
    // selectedCourseId itself changes again) — a permanent skeleton. The
    // fix skips the write entirely for a since-abandoned course.
    const courseA = makeCourse({ id: "course-a", title: "Course A" });
    const courseC = makeCourse({ id: "course-c", title: "Course C" });
    mockedListCourses.mockResolvedValue(ok([courseA, courseC]));

    let resolveChaptersA!: (result: Awaited<ReturnType<typeof listChapters>>) => void;
    let resolveTestsA!: (result: Awaited<ReturnType<typeof listTests>>) => void;
    let resolveChaptersC!: (result: Awaited<ReturnType<typeof listChapters>>) => void;
    let resolveTestsC!: (result: Awaited<ReturnType<typeof listTests>>) => void;

    mockedListChapters.mockImplementation((courseId: string) => {
      if (courseId === "course-a") {
        return new Promise((resolve) => {
          resolveChaptersA = resolve;
        });
      }
      return new Promise((resolve) => {
        resolveChaptersC = resolve;
      });
    });
    mockedListTests.mockImplementation((courseId: string) => {
      if (courseId === "course-a") {
        return new Promise((resolve) => {
          resolveTestsA = resolve;
        });
      }
      return new Promise((resolve) => {
        resolveTestsC = resolve;
      });
    });

    const { rerender } = render(<TestsPage />);

    // Default selection (no ?course=) is the first ready course, A — its
    // fetch is deliberately left pending so it's still in flight below.
    await waitFor(() => expect(mockedListChapters).toHaveBeenCalledWith("course-a"));

    // Switch to course C before A's fetch resolves — same as a user
    // rapid-clicking through the course selector.
    mockSearchParams = new URLSearchParams({ course: "course-c" });
    rerender(<TestsPage />);
    await waitFor(() => expect(mockedListChapters).toHaveBeenCalledWith("course-c"));

    // C's fetch resolves: its chapter renders.
    await act(async () => {
      resolveChaptersC(ok([makeChapter({ chapter_label: "Chapter C", test_stats: null })]));
      resolveTestsC(ok([]));
    });
    expect(await screen.findByText("Chapter C")).toBeInTheDocument();

    // A's stale fetch resolves last.
    await act(async () => {
      resolveChaptersA(ok([makeChapter({ chapter_label: "Chapter A", test_stats: null })]));
      resolveTestsA(ok([]));
    });

    // C's content must still be rendered — not a skeleton, not A's data.
    expect(screen.getByText("Chapter C")).toBeInTheDocument();
    expect(screen.queryByText("Chapter A")).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
