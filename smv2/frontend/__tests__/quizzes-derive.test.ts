import { describe, expect, it } from "vitest";

import { deriveQuizItems, QUIZ_RETAKE_THRESHOLD, type CourseChapters } from "@/lib/dashboard/quizzes";
import type { ChapterOut } from "@/lib/api/client";

// ChapterOut has no separate "title" field — chapter_label doubles as the
// display title (verified: backend/app/db/models.py's own doc comment says
// "chapter_label is the exact title of the chapter-marker section"). This
// fixture builds a real ChapterOut shape (no `as never` escape hatch needed).
function chapter(
  label: string | null,
  attempts: number,
  best: number | null,
): ChapterOut {
  return {
    chapter_label: label,
    section_ids: [],
    practice_section_ids: [],
    answers_section_ids: [],
    test_stats: { attempts, best_score: best, latest_score: best },
  };
}

function entry(chapters: ChapterOut[]): CourseChapters[] {
  return [{ courseId: "c1", courseTitle: "T", chapters }];
}

describe("deriveQuizItems", () => {
  it("flags never-attempted chapters (legacy {attempts:0} shape)", () => {
    const items = deriveQuizItems(entry([chapter("1", 0, null)]));
    expect(items).toEqual([
      expect.objectContaining({ courseId: "c1", chapterLabel: "1", reason: "not_attempted" }),
    ]);
  });

  it("flags never-attempted chapters when test_stats is null — the real shape the backend returns", () => {
    // Verified: chapters_service.get_chapters only creates a stats_by_label
    // entry when at least one TestAttempt row exists for that chapter_label;
    // a chapter with zero attempts ever comes back with test_stats: null,
    // never {attempts: 0, ...}.
    const items = deriveQuizItems(
      entry([{ ...chapter("1", 0, null), test_stats: null }]),
    );
    expect(items).toEqual([
      expect.objectContaining({ chapterLabel: "1", reason: "not_attempted", bestScore: null }),
    ]);
  });

  it("flags low best score, boundary exclusive", () => {
    const items = deriveQuizItems(
      entry([
        chapter("1", 2, QUIZ_RETAKE_THRESHOLD), // at threshold: NOT flagged
        chapter("2", 2, QUIZ_RETAKE_THRESHOLD - 0.1), // below: flagged
      ]),
    );
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ chapterLabel: "2", reason: "retake" });
  });

  it("does not flag an attempted-but-ungraded chapter (attempts > 0, best_score null)", () => {
    // A real, reachable state: an attempt exists but nothing is graded yet
    // (e.g. an in-progress attempt) — not "never attempted", and we don't
    // know the score, so it should not surface as a retake either.
    const items = deriveQuizItems(entry([chapter("1", 1, null)]));
    expect(items).toEqual([]);
  });

  it("skips chapters with a null chapter_label (front matter — nothing to link/test)", () => {
    const items = deriveQuizItems(entry([chapter(null, 0, null)]));
    expect(items).toEqual([]);
  });

  it("returns empty for empty input", () => {
    expect(deriveQuizItems([])).toEqual([]);
  });

  it("sorts not_attempted before retake, and lowest score first within a reason", () => {
    const items = deriveQuizItems(
      entry([
        chapter("low-retake", 1, 0.1),
        chapter("never", 0, null),
        chapter("high-retake", 1, 0.5),
      ]),
    );
    expect(items.map((item) => item.chapterLabel)).toEqual(["never", "low-retake", "high-retake"]);
  });
});
