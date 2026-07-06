import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ChapterTestClient from "@/components/chapter/ChapterTestClient";
import {
  generateTest,
  getJob,
  getSection,
  listChapters,
  listTests,
  type ChapterOut,
  type JobOut,
  type SectionDetailOut,
  type TestAttemptSummaryOut,
} from "@/lib/api/client";

import { err, ok } from "./support/api-result";
import { FakeEventSource } from "./support/fake-event-source";

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  usePathname: () => "/course/course-1/chapter/Chapter%201/test",
}));

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  listChapters: vi.fn(),
  getSection: vi.fn(),
  listTests: vi.fn(),
  generateTest: vi.fn(),
  getJob: vi.fn(),
}));

const mockedListChapters = vi.mocked(listChapters);
const mockedGetSection = vi.mocked(getSection);
const mockedListTests = vi.mocked(listTests);
const mockedGenerateTest = vi.mocked(generateTest);
const mockedGetJob = vi.mocked(getJob);

function makeChapter(overrides: Partial<ChapterOut> = {}): ChapterOut {
  return {
    chapter_label: "Chapter 1",
    section_ids: ["c1-content"],
    practice_section_ids: ["c1-practice"],
    answers_section_ids: ["c1-answers"],
    test_stats: null,
    ...overrides,
  };
}

function makeSectionDetail(overrides: Partial<SectionDetailOut> = {}): SectionDetailOut {
  return {
    id: "c1-practice",
    course_id: "course-1",
    title: "Practice Set",
    order_index: 1,
    page_start: 6,
    page_end: 7,
    kind: "practice",
    chapter_label: "Chapter 1",
    body_md: "Practice question: what is 2+2?",
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

// getSection is called for both practice and answer section ids (see
// ChapterTestClient's loadSections) — this keys the mocked response by the
// requested id so a test that touches both never sees one blank out or
// duplicate the other's text.
function mockGetSectionById(id: string) {
  return Promise.resolve(
    ok(
      makeSectionDetail(
        id === "c1-answers"
          ? { id, kind: "answers", body_md: "Answer: 4" }
          : { id },
      ),
    ),
  );
}

function makeAttempt(overrides: Partial<TestAttemptSummaryOut> = {}): TestAttemptSummaryOut {
  return {
    id: "attempt-1",
    course_id: "course-1",
    chapter_label: "Chapter 1",
    score: 0.75,
    question_count: 4,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeJob(overrides: Partial<JobOut> = {}): JobOut {
  return {
    id: "job-1",
    type: "generate_test",
    status: "running",
    payload: { course_id: "course-1", chapter_label: "Chapter 1" },
    result: null,
    progress: null,
    error: null,
    attempts: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("ChapterTestClient", () => {
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

  it("renders the chapter's practice sections in order", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter()]));
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests.mockResolvedValue(ok([]));

    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    expect(await screen.findByText("Practice question: what is 2+2?")).toBeInTheDocument();
    expect(mockedGetSection).toHaveBeenCalledWith("c1-practice");
  });

  it("renders the chapter's answer key in a collapsed disclosure, revealed on click", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter()]));
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests.mockResolvedValue(ok([]));

    const user = userEvent.setup();
    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);
    await screen.findByText("Practice question: what is 2+2?");

    const summary = screen.getByText("Answer key");
    const details = summary.closest("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");

    await user.click(summary);
    expect(details).toHaveAttribute("open");
    expect(screen.getByText("Answer: 4")).toBeInTheDocument();
  });

  it("shows the 'no practice sections' empty state when the chapter has none", async () => {
    mockedListChapters.mockResolvedValue(
      ok([makeChapter({ practice_section_ids: [], answers_section_ids: [] })]),
    );
    mockedListTests.mockResolvedValue(ok([]));

    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    expect(
      await screen.findByText(/no practice sections detected in this chapter/i),
    ).toBeInTheDocument();
    expect(mockedGetSection).not.toHaveBeenCalled();
  });

  it("shows an error when no chapter matches the given label", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter({ chapter_label: "Chapter 2" })]));
    mockedListTests.mockResolvedValue(ok([]));

    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/no chapter named "chapter 1"/i);
  });

  it("feeds the chapter's test_stats into the mastery bar", async () => {
    mockedListChapters.mockResolvedValue(
      ok([makeChapter({ test_stats: { attempts: 2, best_score: 0.75, latest_score: 0.5 } })]),
    );
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests.mockResolvedValue(ok([makeAttempt()]));

    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    expect(await screen.findByText("Chapter mastery: 75%")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "75");
  });

  it("shows attempt history scoped to this chapter, each linking to its taking/review page", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter()]));
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests.mockResolvedValue(
      ok([
        makeAttempt({ id: "attempt-1", chapter_label: "Chapter 1", score: 0.75 }),
        makeAttempt({ id: "attempt-2", chapter_label: "Chapter 2", score: 0.9 }),
      ]),
    );

    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    const link = await screen.findByRole("link", { name: /75%/i });
    expect(link).toHaveAttribute("href", "/course/course-1/test/attempt-1");
    expect(screen.queryByText("90%")).not.toBeInTheDocument();
  });

  it("generating a test shows live SSE progress, then navigates into the newly created attempt", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter()]));
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests
      .mockResolvedValueOnce(ok([])) // initial history load: none yet
      .mockResolvedValueOnce(ok([makeAttempt({ id: "brand-new-attempt" })])); // after settle
    mockedGenerateTest.mockResolvedValue(ok({ job_id: "job-1" }, 202));

    const user = userEvent.setup();
    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);
    await screen.findByText("Practice question: what is 2+2?");

    await user.click(await screen.findByRole("button", { name: /take chapter test/i }));
    expect(mockedGenerateTest).toHaveBeenCalledWith("course-1", { chapterLabel: "Chapter 1" });

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(screen.getByText(/preparing/i)).toBeInTheDocument();

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-1",
        status: "succeeded",
        progress: { stage: "done", pct: 100, message: "done" },
      });
    });

    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/course/course-1/test/brand-new-attempt"),
    );
  });

  it("shows the job's error text and a retry when generation fails", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter()]));
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests.mockResolvedValue(ok([]));
    mockedGenerateTest
      .mockResolvedValueOnce(ok({ job_id: "job-1" }, 202))
      .mockResolvedValueOnce(ok({ job_id: "job-2" }, 202));
    mockedGetJob.mockResolvedValue(
      ok(makeJob({ status: "failed", error: "ANTHROPIC_API_KEY is not configured" })),
    );

    const user = userEvent.setup();
    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);
    await screen.findByText("Practice question: what is 2+2?");

    await user.click(await screen.findByRole("button", { name: /take chapter test/i }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit("update", { id: "job-1", status: "failed", progress: null });
    });

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/generation failed: anthropic_api_key is not configured/i);

    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(mockedGenerateTest).toHaveBeenCalledTimes(2);
  });

  it("shows a retryable error banner when the chapter itself fails to load", async () => {
    mockedListChapters.mockResolvedValueOnce(err(500)).mockResolvedValueOnce(ok([makeChapter()]));
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests.mockResolvedValue(ok([]));

    const user = userEvent.setup();
    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(/loading chapter/i);

    await user.click(screen.getByRole("button", { name: /retry/i }));
    expect(await screen.findByText("Practice question: what is 2+2?")).toBeInTheDocument();
  });
});
