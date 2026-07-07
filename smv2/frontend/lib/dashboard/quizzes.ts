/**
 * "Quizzes to take" is DERIVED, not scheduled (spec decision 1): a chapter
 * qualifies if it was never attempted or its best score is below the
 * threshold. Pure function — fetching stays in the panel component.
 *
 * Verified facts this derivation relies on (see task-4-report.md for grep
 * evidence):
 *
 * - `ChapterOut` (lib/api/schema.d.ts) has no separate "title" field — only
 *   `chapter_label` (nullable), `section_ids`, `practice_section_ids`,
 *   `answers_section_ids`, `test_stats`. `chapter_label` doubles as the
 *   display title per its own doc comment in backend/app/db/models.py
 *   ("chapter_label is the exact title of the chapter-marker section"), so
 *   `chapterTitle` below is sourced from the same value as `chapterLabel`.
 * - `chapter_label` is nullable (the "Front matter" group). There is
 *   nothing to link or test for that group, so it's skipped entirely —
 *   mirroring the existing precedent in components/dashboard/StudyNextList.tsx.
 * - `best_score` is a 0–1 fraction, not 0–100 (verified: chat_service.py
 *   formats it as `best_score * 100`; study_service.py's own
 *   `_LOW_SCORE_THRESHOLD = 0.6`). QUIZ_RETAKE_THRESHOLD is therefore 0.7.
 * - A chapter with zero attempts ever comes back from the backend with
 *   `test_stats: null`, NOT `{attempts: 0, ...}` — chapters_service.py's
 *   `get_chapters` only creates a stats_by_label entry when iterating an
 *   actual TestAttempt row, so a chapter_label with no attempts never gets
 *   one. Treat both `!stats` and `stats.attempts === 0` as "never attempted".
 * - An attempted-but-ungraded chapter (attempts > 0, best_score null) is
 *   neither "never attempted" nor a known-low score, so it is not flagged.
 */
import type { ChapterOut } from "@/lib/api/client";

export const QUIZ_RETAKE_THRESHOLD = 0.7;

export interface CourseChapters {
  courseId: string;
  courseTitle: string;
  chapters: ChapterOut[];
}

export interface QuizItem {
  courseId: string;
  courseTitle: string;
  chapterLabel: string;
  chapterTitle: string;
  reason: "not_attempted" | "retake";
  bestScore: number | null;
}

export function deriveQuizItems(entries: CourseChapters[]): QuizItem[] {
  const items: QuizItem[] = [];
  for (const { courseId, courseTitle, chapters } of entries) {
    for (const ch of chapters) {
      if (ch.chapter_label === null) continue; // front matter: nothing to link/test
      const stats = ch.test_stats;
      if (!stats || stats.attempts === 0) {
        items.push({
          courseId,
          courseTitle,
          chapterLabel: ch.chapter_label,
          chapterTitle: ch.chapter_label,
          reason: "not_attempted",
          bestScore: null,
        });
      } else if (stats.best_score != null && stats.best_score < QUIZ_RETAKE_THRESHOLD) {
        items.push({
          courseId,
          courseTitle,
          chapterLabel: ch.chapter_label,
          chapterTitle: ch.chapter_label,
          reason: "retake",
          bestScore: stats.best_score,
        });
      }
    }
  }
  // not_attempted first, then lowest score first — most actionable at top
  return items.sort((a, b) =>
    a.reason === b.reason
      ? (a.bestScore ?? -1) - (b.bestScore ?? -1)
      : a.reason === "not_attempted"
        ? -1
        : 1,
  );
}
