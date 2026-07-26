import { describe, expect, it } from "vitest";

import type { CourseOut, StudyNextItemOut } from "@/lib/api/client";
import { buildTaskCards } from "@/lib/dashboard/taskCards";
import type { ChapterInfo } from "@/lib/dashboard/useContinueChapter";

function makeCourse(overrides: Partial<CourseOut> = {}): CourseOut {
  return {
    id: "course-1",
    title: "Course",
    status: "ready",
    section_count: 4,
    failed_asset_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    progress: null,
    ...overrides,
  };
}

describe("buildTaskCards", () => {
  it("returns no cards when nothing applies", () => {
    expect(
      buildTaskCards({
        continueCourse: null,
        continueChapter: null,
        showReviewCard: false,
        reviewCardDueCount: 0,
        reviewCardHref: "/review",
        studyNext: [],
      }),
    ).toEqual([]);
  });

  it("builds a continue-reading card with a progress bar when a chapter has resolved", () => {
    const course = makeCourse({ id: "a", title: "Distributed Systems" });
    const chapter: ChapterInfo = { title: "Consensus", percent: 42 };

    const cards = buildTaskCards({
      continueCourse: course,
      continueChapter: chapter,
      showReviewCard: false,
      reviewCardDueCount: 0,
      reviewCardHref: "/review",
      studyNext: [],
    });

    expect(cards).toEqual([
      {
        id: "continue",
        title: "Keep reading — Consensus",
        meta: "Distributed Systems · 42% through",
        progressPercent: 42,
        actionLabel: "Resume",
        actionHref: "/course/a",
        actionVariant: "primary",
      },
    ]);
  });

  it("falls back to the course title (no percent) when the chapter hasn't resolved yet", () => {
    const course = makeCourse({ id: "a", title: "Distributed Systems" });

    const cards = buildTaskCards({
      continueCourse: course,
      continueChapter: null,
      showReviewCard: false,
      reviewCardDueCount: 0,
      reviewCardHref: "/review",
      studyNext: [],
    });

    expect(cards[0].title).toBe("Keep reading — Distributed Systems");
    expect(cards[0].meta).toBe("Distributed Systems");
    expect(cards[0].progressPercent).toBeUndefined();
  });

  it("adds a review card when due cards are shown", () => {
    const cards = buildTaskCards({
      continueCourse: null,
      continueChapter: null,
      showReviewCard: true,
      reviewCardDueCount: 1,
      reviewCardHref: "/review?course=a&start=due",
      studyNext: [],
    });

    expect(cards).toEqual([
      {
        id: "review",
        title: "Review 1 due flashcard",
        meta: "1 card due for review",
        actionLabel: "Start review",
        actionHref: "/review?course=a&start=due",
        actionVariant: "secondary",
      },
    ]);
  });

  it("adds a retake-test card from the primary course's first low_test_score suggestion", () => {
    const course = makeCourse({ id: "a" });
    const studyNext: StudyNextItemOut[] = [
      { chapter_label: "Chapter 2", reason: "due_cards", detail: { due_count: 3 } },
      { chapter_label: "Chapter 1", reason: "low_test_score", detail: { best_score: 0.4 } },
    ];

    const cards = buildTaskCards({
      continueCourse: course,
      continueChapter: null,
      showReviewCard: false,
      reviewCardDueCount: 0,
      reviewCardHref: "/review",
      studyNext,
    });

    expect(cards[cards.length - 1]).toEqual({
      id: "retake",
      title: "Beat your 40% on Chapter 1",
      meta: "Same questions, retake anytime · your weakest chapter",
      actionLabel: "Retake test",
      actionHref: "/course/a/chapter/Chapter%201/test",
      actionVariant: "secondary",
    });
  });

  it("ignores a low_test_score suggestion with no chapter to link to, and with no best_score falls back to a scoreless title", () => {
    const course = makeCourse({ id: "a" });
    const studyNext: StudyNextItemOut[] = [
      { chapter_label: null, reason: "low_test_score", detail: { best_score: 0.4 } },
      { chapter_label: "Chapter 3", reason: "low_test_score", detail: {} },
    ];

    const cards = buildTaskCards({
      continueCourse: course,
      continueChapter: null,
      showReviewCard: false,
      reviewCardDueCount: 0,
      reviewCardHref: "/review",
      studyNext,
    });

    expect(cards[cards.length - 1].title).toBe("Retake the Chapter 3 test");
  });

  it("caps the list at 3 cards, in continue/review/retake priority order", () => {
    const course = makeCourse({ id: "a", title: "Course A" });
    const chapter: ChapterInfo = { title: "Ch", percent: 10 };
    const studyNext: StudyNextItemOut[] = [
      { chapter_label: "Chapter 1", reason: "low_test_score", detail: { best_score: 0.2 } },
    ];

    const cards = buildTaskCards({
      continueCourse: course,
      continueChapter: chapter,
      showReviewCard: true,
      reviewCardDueCount: 4,
      reviewCardHref: "/review",
      studyNext,
    });

    expect(cards.map((c) => c.id)).toEqual(["continue", "review", "retake"]);
  });

  it("does not attach a retake card when there is no primary course, even if studyNext has one queued", () => {
    const cards = buildTaskCards({
      continueCourse: null,
      continueChapter: null,
      showReviewCard: false,
      reviewCardDueCount: 0,
      reviewCardHref: "/review",
      studyNext: [{ chapter_label: "Chapter 1", reason: "low_test_score", detail: { best_score: 0.1 } }],
    });

    expect(cards).toEqual([]);
  });
});
