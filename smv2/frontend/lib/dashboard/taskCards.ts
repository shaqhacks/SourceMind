/**
 * "Today's study plan" task-card list (redesign handoff §1 Home). Pure
 * derivation — data fetching stays in app/page.tsx, this only shapes it.
 *
 * Three signal sources, each already used elsewhere on the dashboard, kept
 * in this fixed priority so the plan always leads with the most concrete
 * next step:
 *   1. Continue reading — reuses useContinueChapter's {title, percent} for
 *      the primary in-progress course (same source ContinueCard/StatsRow
 *      used before the redesign). The only card type with a real
 *      percent-through value, so it's the only one that ever carries a
 *      progress bar.
 *   2. Review due cards — reuses the existing due-count/href derivation
 *      from app/page.tsx (unchanged from the pre-redesign ReviewCard).
 *   3. Retake the weakest test — the first `low_test_score` suggestion
 *      study_service.study_next returns for the primary course.
 *
 * Deliberately NOT padded to 3 with study_next's `due_cards`/`unread`/
 * `stale` tiers when fewer than 3 signals apply — inventing a 4th card
 * type not in the mock isn't worth the complexity; an honest shorter list
 * (or empty) beats a manufactured one.
 */
import type { CourseOut, StudyNextItemOut } from "@/lib/api/client";
import type { ChapterInfo } from "@/lib/dashboard/useContinueChapter";

export interface TaskCard {
  id: string;
  title: string;
  meta: string;
  /** Only set for the continue-reading card — the sole type with a real percent. */
  progressPercent?: number;
  actionLabel: string;
  actionHref: string;
  actionVariant: "primary" | "secondary";
}

export interface BuildTaskCardsInput {
  continueCourse: CourseOut | null;
  continueChapter: ChapterInfo | null;
  showReviewCard: boolean;
  reviewCardOverdueCount: number;
  reviewCardHref: string;
  studyNext: StudyNextItemOut[];
}

const MAX_TASK_CARDS = 3;

export function buildTaskCards({
  continueCourse,
  continueChapter,
  showReviewCard,
  reviewCardOverdueCount,
  reviewCardHref,
  studyNext,
}: BuildTaskCardsInput): TaskCard[] {
  const cards: TaskCard[] = [];

  if (continueCourse) {
    cards.push({
      id: "continue",
      title: continueChapter
        ? `Keep reading — ${continueChapter.title}`
        : `Keep reading — ${continueCourse.title}`,
      meta: continueChapter
        ? `${continueCourse.title} · ${continueChapter.percent}% through`
        : continueCourse.title,
      progressPercent: continueChapter?.percent,
      actionLabel: "Resume",
      actionHref: `/course/${continueCourse.id}`,
      actionVariant: "primary",
    });
  }

  if (showReviewCard) {
    const n = reviewCardOverdueCount;
    cards.push({
      id: "review",
      title: `Review ${n} due flashcard${n === 1 ? "" : "s"}`,
      meta: `${n} card${n === 1 ? "" : "s"} due for review`,
      actionLabel: "Start review",
      actionHref: reviewCardHref,
      actionVariant: "secondary",
    });
  }

  const retake = continueCourse
    ? studyNext.find((item) => item.reason === "low_test_score" && item.chapter_label !== null)
    : undefined;
  if (retake && continueCourse) {
    const bestScore = retake.detail.best_score;
    const pct = typeof bestScore === "number" ? Math.round(bestScore * 100) : null;
    cards.push({
      id: "retake",
      title: pct != null
        ? `Beat your ${pct}% on ${retake.chapter_label}`
        : `Retake the ${retake.chapter_label} test`,
      meta: "Same questions, retake anytime · your weakest chapter",
      actionLabel: "Retake test",
      actionHref: `/course/${continueCourse.id}/chapter/${encodeURIComponent(retake.chapter_label ?? "")}/test`,
      actionVariant: "secondary",
    });
  }

  return cards.slice(0, MAX_TASK_CARDS);
}
