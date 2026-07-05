/**
 * Pure logic for the dashboard's "Continue reading" card. CourseOut already
 * embeds a ProgressSummary (section_id/scroll_pos/updated_at) per course —
 * listCourses() alone is enough to pick the most-recently-read course,
 * with no extra per-course get_progress round trip needed.
 */

import type { CourseOut } from "@/lib/api/client";

export function pickMostRecentCourse(courses: CourseOut[]): CourseOut | null {
  const candidates = courses.filter(
    (course) => course.progress?.section_id != null && course.progress.updated_at != null,
  );
  if (candidates.length === 0) return null;

  return candidates.reduce((latest, course) => {
    const courseUpdatedAt = new Date(course.progress!.updated_at as string).getTime();
    const latestUpdatedAt = new Date(latest.progress!.updated_at as string).getTime();
    return courseUpdatedAt > latestUpdatedAt ? course : latest;
  });
}

/** 1-based "chapter N of M" position, as a percentage. */
export function percentComplete(orderIndex: number, sectionCount: number): number {
  if (sectionCount <= 0) return 0;
  return Math.round(((orderIndex + 1) / sectionCount) * 100);
}
