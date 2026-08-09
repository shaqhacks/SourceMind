import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReadingColumn from "@/components/reader/ReadingColumn";
import {
  findActiveCardsJob,
  getReviewQueue,
  listCards,
  listHighlights,
  type CardOut,
  type ReviewQueueCardOut,
} from "@/lib/api/client";
import type { ReaderSection, SectionBodyState } from "@/lib/reader/types";

import { ok } from "./support/api-result";

vi.mock("@/lib/api/client", () => ({
  listNotes: vi.fn(() => Promise.resolve({ data: [], ok: true, status: 200 })),
  listHighlights: vi.fn(),
  createHighlight: vi.fn(),
  updateHighlight: vi.fn(),
  deleteHighlight: vi.fn(),
  listCards: vi.fn(),
  findActiveCardsJob: vi.fn(),
  getReviewQueue: vi.fn(),
}));

vi.mock("@/lib/review/gradeCardAndNotify", () => ({
  gradeCardAndNotify: vi.fn(),
}));

vi.mock("@/components/reader/PagesView", () => ({
  default: () => <p>Original pages stub</p>,
}));

const mockedListHighlights = vi.mocked(listHighlights);
const mockedListCards = vi.mocked(listCards);
const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);
const mockedGetReviewQueue = vi.mocked(getReviewQueue);

const SECTION: ReaderSection = {
  id: "sec-1",
  title: "Ratios",
  order_index: 0,
  page_start: null,
  page_end: null,
  lesson_status: "none",
  has_content: true,
  word_count: 100,
  kind: "content",
  chapter_label: "Fractions & Ratios",
  asset_id: null,
};

const BODY: SectionBodyState = { kind: "ready", body: "# Ratios\n\nSource body." };

function makeCard(overrides: Partial<CardOut> = {}): CardOut {
  return {
    id: "card-1",
    section_id: "sec-1",
    front_md: "Reader card",
    back_md: "Reader answer",
    position: 0,
    origin: "generated",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeReviewCard(overrides: Partial<ReviewQueueCardOut> = {}): ReviewQueueCardOut {
  return {
    id: "card-1",
    section_id: "sec-1",
    front_md: "Reader card",
    back_md: "Reader answer",
    due_at: null,
    is_new: true,
    interval_days: 1,
    ease: 2.5,
    reps: 0,
    chapter_label: "Fractions & Ratios",
    section_title: "Ratios",
    is_due: false,
    last_grade: null,
    ...overrides,
  };
}

function renderColumn(section: ReaderSection = SECTION) {
  return render(
    <ReadingColumn
      courseId="course-1"
      section={section}
      mode="source"
      typography={{ fontSize: 18, measure: 78, lineHeight: 1.6 }}
      headingRef={{ current: null }}
      columnRef={{ current: null }}
      body={BODY}
      onLessonStatusChange={vi.fn()}
      onNext={vi.fn()}
      onPrevious={vi.fn()}
      nextTitle={null}
      previousTitle={null}
      onExplainSelection={vi.fn()}
    />,
  );
}

describe("ReadingColumn card review context", () => {
  beforeEach(() => {
    mockedListHighlights.mockResolvedValue(ok([]));
    mockedFindActiveCardsJob.mockResolvedValue(null);
    mockedListCards.mockResolvedValue(ok([makeCard()]));
    mockedGetReviewQueue.mockResolvedValue(
      ok({
        due: 0,
        new: 1,
        due_count: 0,
        new_count: 1,
        overdue_count: 0,
        available_count: 1,
        total: 1,
        total_count: 1,
        cards: [makeReviewCard()],
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("passes the active section chapter label to SectionCards", async () => {
    renderColumn();

    expect(await screen.findByRole("link", { name: "Review this chapter" })).toHaveAttribute(
      "href",
      "/review?course=course-1&scope=all&chapter=Fractions%20%26%20Ratios",
    );
    await waitFor(() =>
      expect(mockedGetReviewQueue).toHaveBeenCalledWith("course-1", {
        scope: "all",
        chapterLabel: "Fractions & Ratios",
        limit: 200,
      }),
    );
  });
});
