import type { JobOut, TestAttemptSummaryOut, TestSummaryOut } from "@/lib/api/client";

/** Design-literal threshold for this screen's ring/verdict color split
 * (sage ≥80%, accent <80% — per the redesign handoff §5). Deliberately
 * distinct from lib/dashboard/quizzes.ts's QUIZ_RETAKE_THRESHOLD (0.7),
 * which drives a different surface (Home's "quizzes to take" list) and is
 * out of scope to change here. */
export const SOLID_THRESHOLD = 0.8;

export function toPercent(score: number): number {
  return Math.round(score * 100);
}

/** "today" / "yesterday" / "N days ago" / a short date once it's stale
 * enough that a relative count stops being useful at a glance. */
export function formatRelativeDate(iso: string): string {
  const then = new Date(iso);
  const now = new Date();
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((startOfDay(now) - startOfDay(then)) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 14) return `${days} days ago`;
  return then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/** All attempts across every deck generated for one chapter, newest first —
 * a chapter can have several Test decks (each "New test" regenerates one)
 * so a chapter-level view has to flatten across them to find the true
 * latest attempt, not just the latest deck's own attempts. */
export function attemptsForChapter(
  tests: TestSummaryOut[],
  chapterLabel: string,
): { test: TestSummaryOut; attempt: TestAttemptSummaryOut }[] {
  return tests
    .filter((test) => test.chapter_label === chapterLabel)
    .flatMap((test) => test.attempts.map((attempt) => ({ test, attempt })))
    .sort((a, b) => Date.parse(b.attempt.created_at) - Date.parse(a.attempt.created_at));
}

function payloadChapterLabel(payload: { [key: string]: unknown } | null | undefined): string | null {
  return payload && typeof payload.chapter_label === "string" ? payload.chapter_label : null;
}

function payloadCourseId(payload: { [key: string]: unknown } | null | undefined): string | null {
  return payload && typeof payload.course_id === "string" ? payload.course_id : null;
}

/** Same rediscovery need as findActiveTestJob (lib/api/client.ts), scoped
 * down to one chapter — generate_test's payload carries chapter_label for
 * a chapter-scoped request, so an in-flight job for Chapter 2 doesn't show
 * up on Chapter 1's card. */
export function findActiveChapterTestJob(
  jobs: JobOut[],
  courseId: string,
  chapterLabel: string,
  terminalStatuses: Set<string>,
): JobOut | null {
  const matches = jobs.filter(
    (job) =>
      job.type === "generate_test" &&
      !terminalStatuses.has(job.status) &&
      payloadCourseId(job.payload) === courseId &&
      payloadChapterLabel(job.payload) === chapterLabel,
  );
  if (matches.length === 0) return null;
  return matches.reduce((latest, job) =>
    Date.parse(job.created_at) > Date.parse(latest.created_at) ? job : latest,
  );
}
