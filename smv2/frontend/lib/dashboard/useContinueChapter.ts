import { useEffect, useState } from "react";

import { listSections, type CourseOut } from "@/lib/api/client";
import { percentComplete } from "@/lib/dashboard/continue";

export interface ChapterInfo {
  title: string;
  percent: number;
}

/**
 * Shared "resume point" derivation for both the Continue card and the
 * dashboard's StatsRow: one list_sections call (not carried on CourseOut)
 * turns the saved progress.section_id into a chapter title + position-
 * among-content-sections percentage. Lives here (not in continue.ts) so
 * that module stays a pure, React-free unit — this is the only hook-bearing
 * piece and both call sites share this one implementation.
 *
 * Returns null until sections load, or when there is no saved section to
 * resume from (course is null, or has no progress.section_id).
 */
export function useContinueChapter(course: CourseOut | null): ChapterInfo | null {
  const [chapter, setChapter] = useState<ChapterInfo | null>(null);
  // Depend on primitives, not the CourseOut object: continueCourse is
  // recomputed every render (pickMostRecentCourse) even when the underlying
  // course hasn't changed, so keying the effect on the object identity would
  // refetch needlessly. The id/sectionId pair is what actually matters.
  const courseId = course?.id ?? null;
  const sectionId = course?.progress?.section_id ?? null;

  useEffect(() => {
    if (!courseId || !sectionId) return;
    let active = true;
    listSections(courseId).then(({ data }) => {
      if (!active || !data) return;
      const section = data.find((candidate) => candidate.id === sectionId);
      if (!section) return;

      // Percent complete is measured against content sections only —
      // practice/answers aren't part of the reading flow (see Sidebar/
      // CourseReader), so counting them here would understate progress.
      const contentSections = data
        .filter((candidate) => candidate.kind === "content")
        .sort((a, b) => a.order_index - b.order_index);
      const contentIndex = contentSections.findIndex((candidate) => candidate.id === sectionId);
      setChapter({
        title: section.title,
        percent:
          contentIndex === -1
            ? percentComplete(section.order_index, data.length)
            : percentComplete(contentIndex, contentSections.length),
      });
    });
    return () => {
      active = false;
    };
  }, [courseId, sectionId]);

  return chapter;
}
