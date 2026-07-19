import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CourseReader from "@/components/reader/CourseReader";
import {
  findActiveCardsJob,
  getLlmUsage,
  getSection,
  listAssets,
  listCards,
  listChapters,
  listHighlights,
  listSections,
  type ApiResult,
  type HighlightOut,
} from "@/lib/api/client";
import type { ReaderCourse, ReaderProgress } from "@/lib/reader/types";

import { ok } from "./support/api-result";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
  getSection: vi.fn(),
  saveProgress: vi.fn(),
  getLessonEstimate: vi.fn(),
  findActiveLessonJob: vi.fn(),
  generateLesson: vi.fn(),
  getLlmUsage: vi.fn(),
  getChatHistory: vi.fn(),
  sendChat: vi.fn(),
  listCards: vi.fn(),
  findActiveCardsJob: vi.fn(),
  generateCards: vi.fn(),
  listSections: vi.fn(),
  editOutline: vi.fn(),
  listChapters: vi.fn(),
  listAssets: vi.fn(),
  listHighlights: vi.fn(),
  createHighlight: vi.fn(),
  updateHighlight: vi.fn(),
  deleteHighlight: vi.fn(),
  buildAssetFileUrl: vi.fn((assetId: string) => `https://mock/api/assets/${assetId}/file`),
  buildAssetHtmlPageUrl: vi.fn(
    (assetId: string, page: number) => `https://mock/api/assets/${assetId}/html/${page}`,
  ),
  getAssetHtmlManifest: vi.fn(),
}));

// Same guard as course-reader.test.tsx: the reader tree imports PagesView ->
// PdfPagesView -> pdfjs-dist at module scope, which jsdom can't evaluate.
vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerPort: null },
  getDocument: vi.fn(),
  TextLayer: class {
    render = vi.fn(() => Promise.resolve());
    cancel = vi.fn();
  },
}));

const mockedGetSection = vi.mocked(getSection);
const mockedGetLlmUsage = vi.mocked(getLlmUsage);
const mockedListCards = vi.mocked(listCards);
const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);
const mockedListSections = vi.mocked(listSections);
const mockedListChapters = vi.mocked(listChapters);
const mockedListAssets = vi.mocked(listAssets);
const mockedListHighlights = vi.mocked(listHighlights);

// Two sections whose rendered text BOTH contain the phrase "example
// passage" — this is what lets a stale, previous-section highlight resolve
// (wrongly) against the new section's DOM via rangeForSelector's plain
// exact-text + occurrence match (it has no section_id check of its own).
const COURSE: ReaderCourse = {
  id: "course-hl",
  title: "Highlight Course",
  sections: [
    {
      id: "sec-1",
      title: "Chapter One",
      order_index: 0,
      page_start: 1,
      page_end: 5,
      lesson_status: "none",
      has_content: true,
      word_count: 100,
      kind: "content",
      chapter_label: null,
      asset_id: null,
    },
    {
      id: "sec-2",
      title: "Chapter Two",
      order_index: 1,
      page_start: 6,
      page_end: 10,
      lesson_status: "none",
      has_content: true,
      word_count: 120,
      kind: "content",
      chapter_label: null,
      asset_id: null,
    },
  ],
};

const BODIES: Record<string, string> = {
  "sec-1": "# Chapter One\n\nRead the example passage below for context.",
  "sec-2": "# Chapter Two\n\nThis chapter also has an example passage in it.",
};

const NO_PROGRESS: ReaderProgress = { section_id: null, scroll_pos: 0 };

function makeHighlight(overrides: Partial<HighlightOut>): HighlightOut {
  return {
    id: "hl-base",
    course_id: "course-hl",
    section_id: "sec-1",
    exact: "example passage",
    prefix: "",
    suffix: "",
    occurrence: 0,
    page: null,
    color: "yellow",
    surface: "source",
    note_md: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

// A highlight that genuinely belongs to sec-1, whose `exact` phrase ALSO
// occurs (at the same occurrence index) in sec-2's body — the setup that
// lets a stale useHighlights state bleed a foreign-section highlight onto
// real, visible text if ReadingColumn ever stops scoping by section.id.
const SEC1_HIGHLIGHT = makeHighlight({ id: "hl-sec1", section_id: "sec-1", color: "yellow" });
const SEC2_HIGHLIGHT = makeHighlight({ id: "hl-sec2", section_id: "sec-2", color: "green" });

/** A promise plus external resolve/reject, for controlling exactly when a
 * mocked async call settles relative to test assertions. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("ReadingColumn highlight painting across a section change", () => {
  beforeEach(() => {
    mockedGetSection.mockImplementation((id: string) => {
      const section = COURSE.sections.find((candidate) => candidate.id === id);
      if (!section) throw new Error(`unexpected section id ${id}`);
      return Promise.resolve(
        ok({
          id: section.id,
          course_id: COURSE.id,
          title: section.title,
          order_index: section.order_index,
          page_start: section.page_start,
          page_end: section.page_end,
          kind: section.kind,
          chapter_label: section.chapter_label,
          asset_id: section.asset_id,
          body_md: BODIES[id],
          content_hash: "hash",
          lesson_md: null,
          lesson_status: section.lesson_status,
          lesson_stale: false,
          lesson_model: null,
          lesson_prompt_version: null,
          extractor_version: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });
    mockedGetLlmUsage.mockResolvedValue(
      ok({ calls: 0, input_tokens: 0, output_tokens: 0, est_cost_usd: 0 }),
    );
    mockedListCards.mockResolvedValue(ok([]));
    mockedFindActiveCardsJob.mockResolvedValue(null);
    mockedListAssets.mockResolvedValue(ok([]));
    mockedListSections.mockResolvedValue(ok(COURSE.sections));
    mockedListChapters.mockResolvedValue(ok([]));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    window.localStorage.clear();
    for (const name of ["hl-yellow", "hl-green", "hl-blue", "hl-pink"]) {
      CSS.highlights.delete(name);
    }
  });

  it("does not paint a foreign-section highlight while its section's own highlights are still loading", async () => {
    const initialLoad = Promise.resolve(ok([SEC1_HIGHLIGHT, SEC2_HIGHLIGHT]));
    const secondLoad = deferred<ApiResult<HighlightOut[]>>();
    // First call: the mount-time fetch for sec-1, resolves immediately.
    // Second call: fired when the active section changes to sec-2 (see
    // useHighlights' effect deps) — held pending on purpose so the test can
    // assert the state where sec-2's body is ready but its highlights
    // fetch has NOT yet resolved (the exact race the bug report describes).
    mockedListHighlights.mockImplementationOnce(() => initialLoad);
    mockedListHighlights.mockImplementationOnce(() => secondLoad.promise);

    const user = userEvent.setup();
    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    await screen.findByText(/read the example passage/i);

    // Sanity check: sec-1's own highlight paints correctly before any
    // navigation happens.
    expect(CSS.highlights.get("hl-yellow")?.size).toBe(1);

    await user.click(screen.getByRole("button", { name: "Next chapter: Chapter Two" }));
    await screen.findByText(/this chapter also has an example passage/i);

    // sec-2's body is ready, but the second listHighlights() call (fired by
    // the section change) is still pending — useHighlights' `highlights`
    // state therefore still holds sec-1's filtered rows. Without
    // ReadingColumn's own section.id filter, hl-sec1's "example passage"
    // selector would resolve against sec-2's DOM (same phrase, same
    // occurrence) and paint yellow onto text that isn't actually
    // highlighted. It must not.
    expect(CSS.highlights.get("hl-yellow")).toBeUndefined();
    expect(CSS.highlights.get("hl-green")).toBeUndefined();

    // Once the fetch catches up, the registry reflects ONLY sec-2's own
    // highlight — no bleed from sec-1, and no leftover stale entry either.
    secondLoad.resolve(ok([SEC1_HIGHLIGHT, SEC2_HIGHLIGHT]));
    await waitFor(() => {
      expect(CSS.highlights.get("hl-green")?.size).toBe(1);
    });
    expect(CSS.highlights.get("hl-yellow")).toBeUndefined();
  });
});
