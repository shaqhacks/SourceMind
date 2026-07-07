"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { getStudyNext, type StudyNextItemOut } from "@/lib/api/client";

export interface StudyNextListProps {
  courseId: string;
}

// study_service.study_next (ADR-022) already caps at 3 and orders by
// priority tier — this is a defensive backstop, not the primary limit.
const MAX_SUGGESTIONS = 3;

// Human-readable chip text per reason, using the numbers already in
// `detail` (best_score/due_count/days_since) rather than a bare label —
// see study_service.py's own docstring for what each reason/detail pair
// means.
function reasonLabel(item: StudyNextItemOut): string {
  switch (item.reason) {
    case "low_test_score": {
      const bestScore = item.detail.best_score;
      return typeof bestScore === "number"
        ? `low test score (${Math.round(bestScore * 100)}%)`
        : "low test score";
    }
    case "due_cards": {
      const dueCount = item.detail.due_count;
      return typeof dueCount === "number" ? `${dueCount} cards piling up` : "cards piling up";
    }
    case "unread":
      return "unread";
    case "stale": {
      const daysSince = item.detail.days_since;
      return typeof daysSince === "number" ? `not reviewed in ${daysSince}d` : "hasn't been reviewed in a while";
    }
    default:
      return item.reason;
  }
}

// low_test_score points at the chapter's test page (the thing to
// retake); due_cards points straight into a due-now review session
// (reuses the ?start=due entry point); unread/stale point at the
// chapter's own reading page.
function suggestionHref(courseId: string, item: StudyNextItemOut): string {
  if (item.reason === "low_test_score") {
    return `/course/${courseId}/chapter/${encodeURIComponent(item.chapter_label ?? "")}/test`;
  }
  if (item.reason === "due_cards") {
    return `/review?course=${courseId}&start=due`;
  }
  return `/course/${courseId}`;
}

/**
 * Top study-next suggestions for the dashboard's primary course (the same
 * one ContinueCard/ReviewCard are about) — deterministic display of
 * whatever the backend returns, in its own order; the only client-side
 * operation is truncating to the top 3, nothing is re-sorted or
 * re-filtered here.
 */
export default function StudyNextList({ courseId }: StudyNextListProps) {
  const [suggestions, setSuggestions] = useState<StudyNextItemOut[]>([]);

  useEffect(() => {
    let active = true;
    getStudyNext(courseId).then(({ data }) => {
      // chapter_label is nullable in the schema (mirrors ChapterOut's
      // front-matter convention) but study_service filters those chapters
      // out before ever suggesting them — this guard is belt-and-suspenders
      // against a suggestion with nothing to link to or key a list item by.
      if (active && data) {
        setSuggestions(
          data.filter((item) => item.chapter_label !== null).slice(0, MAX_SUGGESTIONS),
        );
      }
    });
    return () => {
      active = false;
    };
  }, [courseId]);

  if (suggestions.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Study next
      </h2>
      <ul className="flex flex-col gap-1">
        {suggestions.map((item) => (
          <li key={item.chapter_label}>
            <Link
              href={suggestionHref(courseId, item)}
              className="flex items-center justify-between gap-3 rounded-md border border-border px-3 py-2 text-sm hover:bg-muted-foreground/5"
            >
              <span className="font-medium">{item.chapter_label}</span>
              <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
                {reasonLabel(item)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
