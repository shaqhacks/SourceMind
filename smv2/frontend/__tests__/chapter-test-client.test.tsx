import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ChapterTestClient from "@/components/chapter/ChapterTestClient";
import type { PracticeSectionState } from "@/components/chapter/practiceAssessmentState";
import {
  generateTest,
  getJob,
  getSection,
  listChapters,
  listTests,
  retakeTest,
  type ChapterOut,
  type JobOut,
  type SectionDetailOut,
  type TestAttemptSummaryOut,
  type TestSummaryOut,
} from "@/lib/api/client";

import { err, ok } from "./support/api-result";
import { FakeEventSource } from "./support/fake-event-source";

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
  usePathname: () => "/course/course-1/chapter/Chapter%201/test",
}));

vi.mock("next/dynamic", () => ({
  default: () =>
    function DynamicPagesViewMock({
      courseId,
      assetId,
      pageStart,
      pageEnd,
    }: {
      courseId: string;
      assetId: string;
      pageStart: number;
      pageEnd: number;
    }) {
      return (
        <div
          data-testid="pages-view"
          data-course-id={courseId}
          data-asset-id={assetId}
          data-page-start={pageStart}
          data-page-end={pageEnd}
        >
          Original pages
        </div>
      );
    },
}));

vi.mock("@/components/reader/PagesView", () => ({
  default: ({
    courseId,
    assetId,
    pageStart,
    pageEnd,
  }: {
    courseId: string;
    assetId: string;
    pageStart: number;
    pageEnd: number;
  }) => (
    <div
      data-testid="pages-view"
      data-course-id={courseId}
      data-asset-id={assetId}
      data-page-start={pageStart}
      data-page-end={pageEnd}
    >
      Original pages
    </div>
  ),
}));

const inlinePracticeMock = vi.hoisted(() => ({
  callbacks: new Map<string, (state: PracticeSectionState) => void>(),
  retryVersions: new Map<string, number>(),
  startVersions: new Map<string, number>(),
}));

vi.mock("@/components/chapter/InlinePracticeAssessment", () => ({
  default: ({
    courseId,
    sectionId,
    retryVersion = 0,
    startVersion = 0,
    onStateChange,
  }: {
    courseId: string;
    sectionId: string;
    retryVersion?: number;
    startVersion?: number;
    onStateChange?: (state: PracticeSectionState) => void;
  }) => {
    if (onStateChange) {
      inlinePracticeMock.callbacks.set(sectionId, onStateChange);
    } else {
      inlinePracticeMock.callbacks.delete(sectionId);
    }
    inlinePracticeMock.retryVersions.set(sectionId, retryVersion);
    inlinePracticeMock.startVersions.set(sectionId, startVersion);
    return (
      <div
        data-testid="inline-practice-assessment"
        data-course-id={courseId}
        data-section-id={sectionId}
        data-retry-version={retryVersion}
        data-start-version={startVersion}
      >
        Ready practice questions for {sectionId}
      </div>
    );
  },
}));

vi.mock("@/lib/api/client", () => ({
  API_BASE: "http://localhost:8000",
  TERMINAL_JOB_STATUSES: new Set(["succeeded", "failed"]),
  listChapters: vi.fn(),
  getSection: vi.fn(),
  listTests: vi.fn(),
  generateTest: vi.fn(),
  getJob: vi.fn(),
  retakeTest: vi.fn(),
}));

const mockedListChapters = vi.mocked(listChapters);
const mockedGetSection = vi.mocked(getSection);
const mockedListTests = vi.mocked(listTests);
const mockedGenerateTest = vi.mocked(generateTest);
const mockedGetJob = vi.mocked(getJob);
const mockedRetakeTest = vi.mocked(retakeTest);

const readinessDetail = {
  code: "llm_readiness_unavailable",
  failure_category: "ollama_model_unavailable",
  message: "Your configured Ollama model is not present.",
  remediation: "Open Settings and select a currently installed model.",
};

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
    asset_id: null,
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

function makeAttemptSummary(
  overrides: Partial<TestAttemptSummaryOut> = {},
): TestAttemptSummaryOut {
  return {
    id: "attempt-1",
    score: 0.75,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeTest(overrides: Partial<TestSummaryOut> = {}): TestSummaryOut {
  return {
    id: "test-1",
    course_id: "course-1",
    chapter_label: "Chapter 1",
    question_count: 4,
    created_at: "2026-01-01T00:00:00Z",
    attempts: [makeAttemptSummary()],
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
    error_detail: null,
    retryable: true,
    attempts: 0,
    cancel_requested_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function readyPracticeState(sectionId: string, questionCount: number): PracticeSectionState {
  return {
    kind: "ready",
    sectionId,
    questionCount,
    message: null,
    errorDetail: null,
    retryKind: null,
  };
}

function generatingPracticeState(sectionId: string): PracticeSectionState {
  return {
    kind: "generating",
    sectionId,
    questionCount: 0,
    message: "Preparing questions.",
    errorDetail: null,
    retryKind: null,
  };
}

function failedPracticeState(sectionId: string): PracticeSectionState {
  return {
    kind: "failed",
    sectionId,
    questionCount: 0,
    message: "Practice question extraction failed.",
    errorDetail: null,
    retryKind: "restart",
  };
}

function failedPracticeStateWithDetail(
  sectionId: string,
  overrides: Partial<Pick<PracticeSectionState & { kind: "failed" }, "message" | "errorDetail">>,
): PracticeSectionState {
  return {
    kind: "failed",
    sectionId,
    questionCount: 0,
    message: overrides.message ?? "Practice question extraction failed.",
    errorDetail: overrides.errorDetail ?? null,
    retryKind: "restart",
  };
}

function emitPracticeState(sectionId: string, state: PracticeSectionState) {
  act(() => {
    inlinePracticeMock.callbacks.get(sectionId)?.(state);
  });
}

function retryVersionFor(sectionId: string) {
  return inlinePracticeMock.retryVersions.get(sectionId) ?? 0;
}

function startVersionFor(sectionId: string) {
  return inlinePracticeMock.startVersions.get(sectionId) ?? 0;
}

describe("ChapterTestClient", () => {
  let originalEventSource: typeof EventSource;

  beforeEach(() => {
    originalEventSource = globalThis.EventSource;
    FakeEventSource.instances = [];
    inlinePracticeMock.callbacks.clear();
    inlinePracticeMock.retryVersions.clear();
    inlinePracticeMock.startVersions.clear();
    globalThis.EventSource = FakeEventSource as unknown as typeof EventSource;
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    globalThis.EventSource = originalEventSource;
  });

  it("renders an inline assessment and collapsed textbook source for each practice section", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter()]));
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests.mockResolvedValue(ok([]));

    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    const assessment = await screen.findByTestId("inline-practice-assessment");
    expect(assessment).toHaveAttribute("data-course-id", "course-1");
    expect(assessment).toHaveAttribute("data-section-id", "c1-practice");

    const summary = screen.getByText("View textbook source");
    const details = summary.closest("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");
    expect(screen.getByText("Practice question: what is 2+2?")).toBeInTheDocument();
    expect(mockedGetSection).toHaveBeenCalledWith("c1-practice");
  });

  it("aggregates mixed practice readiness and retries only failed sections", async () => {
    mockedListChapters.mockResolvedValue(
      ok([
        makeChapter({
          practice_section_ids: ["sec-ready", "sec-running", "sec-failed"],
        }),
      ]),
    );
    mockedGetSection.mockImplementation((id: string) =>
      Promise.resolve(ok(makeSectionDetail({ id, body_md: `Source for ${id}` }))),
    );
    mockedListTests.mockResolvedValue(ok([]));

    const user = userEvent.setup();
    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    await screen.findByText("Ready practice questions for sec-ready");
    emitPracticeState("sec-ready", readyPracticeState("sec-ready", 4));
    emitPracticeState("sec-running", generatingPracticeState("sec-running"));
    emitPracticeState("sec-failed", failedPracticeState("sec-failed"));

    expect(screen.getByRole("status", { name: "Practice readiness" })).toHaveTextContent(
      "1 of 3 ready · 1 preparing · 1 needs retry",
    );
    expect(screen.getByText("Ready practice questions for sec-ready")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /take chapter test/i })).toBeEnabled();

    const sourceToggle = screen.getAllByText("View textbook source")[0];
    const details = sourceToggle.closest("details");
    expect(details).not.toBeNull();
    await user.click(sourceToggle);
    expect(details).toHaveAttribute("open");

    await user.click(screen.getByRole("button", { name: "Retry failed (1)" }));
    expect(retryVersionFor("sec-failed")).toBe(1);
    expect(retryVersionFor("sec-ready")).toBe(0);
    expect(retryVersionFor("sec-running")).toBe(0);
    expect(screen.getByRole("button", { name: "Retry failed (1)" })).toBeDisabled();

    emitPracticeState("sec-failed", generatingPracticeState("sec-failed"));
    expect(screen.queryByRole("button", { name: /retry failed/i })).not.toBeInTheDocument();
  });

  it("commands all and only not-started children from the chapter action", async () => {
    const user = userEvent.setup();
    mockedListChapters.mockResolvedValue(
      ok([
        makeChapter({
          practice_section_ids: ["practice-start", "practice-ready", "practice-generating"],
        }),
      ]),
    );
    mockedGetSection.mockImplementation((sectionId: string) =>
      Promise.resolve(ok(makeSectionDetail({ id: sectionId }))),
    );
    mockedListTests.mockResolvedValue(ok([]));

    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);
    await screen.findByRole("heading", { name: "Chapter 1 — Chapter test" });

    act(() => {
      inlinePracticeMock.callbacks.get("practice-start")?.({
        kind: "not_started",
        sectionId: "practice-start",
        questionCount: 0,
        message: null,
        errorDetail: null,
        retryKind: "start",
      });
      inlinePracticeMock.callbacks.get("practice-ready")?.(
        readyPracticeState("practice-ready", 3),
      );
      inlinePracticeMock.callbacks.get("practice-generating")?.(
        generatingPracticeState("practice-generating"),
      );
    });

    await user.click(await screen.findByRole("button", { name: "Generate all practice" }));
    const pendingBulkButton = screen.getByRole("button", { name: "Starting practice..." });
    expect(pendingBulkButton).toBeDisabled();
    await user.click(pendingBulkButton);

    expect(startVersionFor("practice-start")).toBe(1);
    expect(startVersionFor("practice-ready")).toBe(0);
    expect(startVersionFor("practice-generating")).toBe(0);
  });

  it("groups failed practice sections by recovery category without exposing raw parser output", async () => {
    mockedListChapters.mockResolvedValue(
      ok([
        makeChapter({
          practice_section_ids: ["sec-invalid-a", "sec-readiness", "sec-invalid-b"],
        }),
      ]),
    );
    mockedGetSection.mockImplementation((id: string) =>
      Promise.resolve(ok(makeSectionDetail({ id, body_md: `Source for ${id}` }))),
    );
    mockedListTests.mockResolvedValue(ok([]));

    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    await screen.findByText("Ready practice questions for sec-invalid-a");
    emitPracticeState(
      "sec-invalid-a",
      failedPracticeStateWithDetail("sec-invalid-a", {
        message: "Parser stack: {\"questions\":\"bad\"}",
        errorDetail: {
          code: "invalid_model_output",
          failure_category: "structured_output_invalid",
          message: "Parser stack: {\"questions\":\"bad\"}",
        },
      }),
    );
    emitPracticeState(
      "sec-readiness",
      failedPracticeStateWithDetail("sec-readiness", {
        message: "Your configured Ollama model is not present.",
        errorDetail: readinessDetail,
      }),
    );
    emitPracticeState(
      "sec-invalid-b",
      failedPracticeStateWithDetail("sec-invalid-b", {
        message: "Raw parser output: ```json bad```",
        errorDetail: {
          code: "invalid_model_output",
          failure_category: "structured_output_invalid",
          message: "Raw parser output: ```json bad```",
        },
      }),
    );

    expect(screen.getByText("2 sections need a valid model response")).toBeInTheDocument();
    expect(screen.getByText("1 section needs model settings")).toBeInTheDocument();
    expect(screen.queryByText(/parser stack/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/raw parser output/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/```json bad```/i)).not.toBeInTheDocument();
  });

  it("continues with ready practice by moving focus to the first ready section", async () => {
    mockedListChapters.mockResolvedValue(
      ok([
        makeChapter({
          practice_section_ids: ["sec-loading", "sec-ready"],
        }),
      ]),
    );
    mockedGetSection.mockImplementation((id: string) =>
      Promise.resolve(ok(makeSectionDetail({ id, body_md: `Source for ${id}` }))),
    );
    mockedListTests.mockResolvedValue(ok([]));
    const scrollIntoView = vi.fn();
    window.HTMLElement.prototype.scrollIntoView = scrollIntoView;

    const user = userEvent.setup();
    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    await screen.findByText("Ready practice questions for sec-ready");
    emitPracticeState("sec-ready", readyPracticeState("sec-ready", 4));

    await user.click(screen.getByRole("button", { name: "Continue with ready (1)" }));

    const heading = screen.getByRole("heading", { name: "Practice section 2" });
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "start" });
    expect(heading).toBeVisible();
    expect(heading).toHaveFocus();
    expect(heading).not.toHaveClass("sr-only");
    expect(heading).not.toHaveClass("outline-none");
  });

  it("ignores stale practice callbacks without overwriting a ready current chapter", async () => {
    mockedListChapters.mockResolvedValue(
      ok([
        makeChapter({ chapter_label: "Chapter 1", practice_section_ids: ["sec-old"] }),
        makeChapter({ chapter_label: "Chapter 2", practice_section_ids: ["sec-new"] }),
      ]),
    );
    mockedGetSection.mockImplementation((id: string) =>
      Promise.resolve(ok(makeSectionDetail({ id, body_md: `Source for ${id}` }))),
    );
    mockedListTests.mockResolvedValue(ok([]));

    const { rerender } = render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);
    await screen.findByText("Ready practice questions for sec-old");
    const oldCallback = inlinePracticeMock.callbacks.get("sec-old");
    expect(oldCallback).toBeDefined();

    rerender(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 2" />);
    await screen.findByText("Ready practice questions for sec-new");
    emitPracticeState("sec-new", readyPracticeState("sec-new", 3));
    expect(screen.getByRole("status", { name: "Practice readiness" })).toHaveTextContent(
      "1 of 1 ready",
    );

    act(() => {
      oldCallback?.(failedPracticeState("sec-old"));
    });

    expect(screen.getByRole("status", { name: "Practice readiness" })).toHaveTextContent(
      "1 of 1 ready",
    );
    expect(screen.queryByRole("button", { name: /retry failed/i })).not.toBeInTheDocument();
  });

  it("clears the aggregate retry guard when two captured failures both leave failed together", async () => {
    mockedListChapters.mockResolvedValue(
      ok([
        makeChapter({
          practice_section_ids: ["sec-a", "sec-b"],
        }),
      ]),
    );
    mockedGetSection.mockImplementation((id: string) =>
      Promise.resolve(ok(makeSectionDetail({ id, body_md: `Source for ${id}` }))),
    );
    mockedListTests.mockResolvedValue(ok([]));

    const user = userEvent.setup();
    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    await screen.findByText("Ready practice questions for sec-a");
    emitPracticeState("sec-a", failedPracticeState("sec-a"));
    emitPracticeState("sec-b", failedPracticeState("sec-b"));

    await user.click(screen.getByRole("button", { name: "Retry failed (2)" }));
    expect(screen.getByRole("button", { name: "Retry failed (2)" })).toBeDisabled();

    act(() => {
      inlinePracticeMock.callbacks.get("sec-a")?.(generatingPracticeState("sec-a"));
      inlinePracticeMock.callbacks.get("sec-b")?.(generatingPracticeState("sec-b"));
    });
    emitPracticeState("sec-a", failedPracticeState("sec-a"));

    expect(screen.getByRole("button", { name: "Retry failed (1)" })).toBeEnabled();
  });

  it("re-enables aggregate retry with refreshed category when a parent retry restart fails", async () => {
    mockedListChapters.mockResolvedValue(
      ok([
        makeChapter({
          practice_section_ids: ["sec-invalid"],
        }),
      ]),
    );
    mockedGetSection.mockImplementation((id: string) =>
      Promise.resolve(ok(makeSectionDetail({ id, body_md: `Source for ${id}` }))),
    );
    mockedListTests.mockResolvedValue(ok([]));

    const user = userEvent.setup();
    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    await screen.findByText("Ready practice questions for sec-invalid");
    emitPracticeState("sec-invalid", failedPracticeState("sec-invalid"));

    await user.click(screen.getByRole("button", { name: "Retry failed (1)" }));
    expect(screen.getByRole("button", { name: "Retry failed (1)" })).toBeDisabled();

    emitPracticeState("sec-invalid", generatingPracticeState("sec-invalid"));
    emitPracticeState(
      "sec-invalid",
      failedPracticeStateWithDetail("sec-invalid", {
        message: "Parser dump: {\"questions\":\"bad\"}",
        errorDetail: {
          code: "invalid_model_output",
          failure_category: "structured_output_invalid",
          message: "The model returned an invalid question format.",
        },
      }),
    );

    expect(screen.getByRole("button", { name: "Retry failed (1)" })).toBeEnabled();
    expect(screen.getByText("1 section needs a valid model response")).toBeInTheDocument();
    expect(screen.queryByText(/parser dump/i)).not.toBeInTheDocument();
  });

  it("renders original pages inside the source disclosure when page metadata is available", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter()]));
    mockedGetSection.mockImplementation((id: string) =>
      Promise.resolve(
        ok(
          makeSectionDetail({
            id,
            body_md: "1) <sup><u>42</u></sup>\n12",
            asset_id: "asset-1",
            page_start: 16,
            page_end: 17,
          }),
        ),
      ),
    );
    mockedListTests.mockResolvedValue(ok([]));

    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    const assessment = await screen.findByTestId("inline-practice-assessment");
    expect(assessment).toHaveAttribute("data-section-id", "c1-practice");
    const summary = screen.getByText("View textbook source");
    const details = summary.closest("details");
    expect(details).not.toBeNull();
    expect(details).not.toHaveAttribute("open");

    const pages = screen.getByTestId("pages-view");
    expect(pages).toHaveAttribute("data-course-id", "course-1");
    expect(pages).toHaveAttribute("data-asset-id", "asset-1");
    expect(pages).toHaveAttribute("data-page-start", "16");
    expect(pages).toHaveAttribute("data-page-end", "17");
    expect(pages.closest("details")).toBe(details);
    expect(screen.queryByText(/42/)).not.toBeInTheDocument();
  });

  it("does not fetch or render learner-facing answer key sections", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter()]));
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests.mockResolvedValue(ok([]));

    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);
    await screen.findByTestId("inline-practice-assessment");

    expect(mockedGetSection).toHaveBeenCalledWith("c1-practice");
    expect(mockedGetSection).not.toHaveBeenCalledWith("c1-answers");
    expect(screen.queryByText("Answer key")).not.toBeInTheDocument();
    expect(screen.queryByText("Answer: 4")).not.toBeInTheDocument();
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

  it("feeds the chapter's test_stats into the score bar", async () => {
    mockedListChapters.mockResolvedValue(
      ok([makeChapter({ test_stats: { attempts: 2, best_score: 0.75, latest_score: 0.5 } })]),
    );
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests.mockResolvedValue(ok([makeTest()]));

    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    expect(await screen.findByText("Best chapter test score: 75%")).toBeInTheDocument();
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "75");
  });

  it("shows test history scoped to this chapter, each attempt linking to its taking/review page", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter()]));
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests.mockResolvedValue(
      ok([
        makeTest({
          id: "test-1",
          chapter_label: "Chapter 1",
          attempts: [makeAttemptSummary({ id: "attempt-1", score: 0.75 })],
        }),
        makeTest({
          id: "test-2",
          chapter_label: "Chapter 2",
          attempts: [makeAttemptSummary({ id: "attempt-2", score: 0.9 })],
        }),
      ]),
    );

    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    const link = await screen.findByRole("link", { name: /75%/i });
    expect(link).toHaveAttribute("href", "/course/course-1/test/attempt-1");
    expect(screen.queryByText("90%")).not.toBeInTheDocument();
  });

  it("retaking a test calls the retake endpoint and navigates straight into the new attempt", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter()]));
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests.mockResolvedValue(
      ok([makeTest({ id: "test-1", attempts: [makeAttemptSummary({ id: "attempt-1" })] })]),
    );
    mockedRetakeTest.mockResolvedValue(ok({ attempt_id: "attempt-2" }));

    const user = userEvent.setup();
    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    await user.click(await screen.findByRole("button", { name: /^retake$/i }));

    expect(mockedRetakeTest).toHaveBeenCalledWith("test-1");
    await waitFor(() =>
      expect(mockPush).toHaveBeenCalledWith("/course/course-1/test/attempt-2"),
    );
  });

  it("labels the generate button 'New test (regenerates)' once a test already exists, distinct from Retake", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter()]));
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests.mockResolvedValue(ok([makeTest()]));

    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);

    expect(await screen.findByRole("button", { name: /new test \(regenerates\)/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^take chapter test$/i })).not.toBeInTheDocument();
  });

  it("generating a test shows live SSE progress, then navigates into the newly created attempt", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter()]));
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests
      .mockResolvedValueOnce(ok([])) // initial history load: none yet
      .mockResolvedValueOnce(
        ok([makeTest({ attempts: [makeAttemptSummary({ id: "brand-new-attempt" })] })]),
      ); // after settle
    mockedGenerateTest.mockResolvedValue(ok({ job_id: "job-1" }, 202));

    const user = userEvent.setup();
    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);
    await screen.findByText("Practice question: what is 2+2?");

    await user.click(await screen.findByRole("button", { name: /take chapter test/i }));
    expect(mockedGenerateTest).toHaveBeenCalledWith("course-1", { chapterLabel: "Chapter 1" });

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(screen.getAllByText("Preparing")).toHaveLength(2);

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

  it("shows queued chapter-test copy until the job streams thinking progress", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter()]));
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests.mockResolvedValue(ok([]));
    mockedGenerateTest.mockResolvedValue(ok({ job_id: "job-queued-test" }));
    mockedGetJob.mockResolvedValue(
      ok(makeJob({ id: "job-queued-test", status: "running", progress: null })),
    );

    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);
    await screen.findByRole("heading", { name: "Chapter 1 — Chapter test" });
    await userEvent.click(screen.getByRole("button", { name: "Take chapter test" }));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit("update", {
        id: "job-queued-test",
        status: "running",
        progress: null,
      });
    });

    expect(await screen.findAllByText("Queued")).toHaveLength(2);
    expect(screen.queryByText(/Thinking/)).not.toBeInTheDocument();
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

  it("routes immediate structured provider readiness failures to Settings without starting a job stream", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter()]));
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests.mockResolvedValue(ok([]));
    mockedGenerateTest.mockResolvedValue({
      status: 503,
      ok: false,
      error: { detail: readinessDetail },
    });

    const user = userEvent.setup();
    render(<ChapterTestClient courseId="course-1" chapterLabel="Chapter 1" />);
    await screen.findByText("Practice question: what is 2+2?");

    await user.click(await screen.findByRole("button", { name: /take chapter test/i }));

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

  it("routes watched-job structured provider readiness failures to Settings and preserves job details", async () => {
    mockedListChapters.mockResolvedValue(ok([makeChapter()]));
    mockedGetSection.mockImplementation(mockGetSectionById);
    mockedListTests.mockResolvedValue(ok([]));
    mockedGenerateTest.mockResolvedValue(ok({ job_id: "job-1" }, 202));
    mockedGetJob.mockResolvedValue(
      ok(
        makeJob({
          status: "failed",
          error: "Your configured Ollama model is not present.",
          error_detail: readinessDetail,
        }),
      ),
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
    expect(banner).toHaveTextContent(/your configured ollama model is not present/i);
    expect(screen.getByRole("link", { name: /open settings/i })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
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
