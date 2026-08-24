"use client";

import Link from "next/link";

import ProgressBar from "@/components/ui/ProgressBar";
import type { CourseOut } from "@/lib/api/client";
import { useContinueChapter } from "@/lib/dashboard/useContinueChapter";

export interface ContinueCardProps {
  course: CourseOut;
}

/**
 * The dashboard's first-priority card: jump straight back into the most
 * recently read course, at its resume point. The chapter title +
 * completion percentage come from the shared useContinueChapter hook (one
 * list_sections call), the same source StatsRow uses.
 */
export default function ContinueCard({ course }: ContinueCardProps) {
  const chapter = useContinueChapter(course);

  return (
    <Link
      href={`/course/${course.id}/read`}
      className="block rounded-lg border border-border bg-accent-soft/60 p-4 transition-colors hover:border-muted-foreground"
    >
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Continue reading
      </p>
      <h2 className="mt-1 text-lg font-semibold">{course.title}</h2>
      {chapter ? (
        <div className="mt-2 flex flex-col gap-2">
          <p className="text-sm text-muted-foreground">
            {chapter.title} — {chapter.percent}% complete
          </p>
          <ProgressBar percent={chapter.percent} label={`Progress through ${course.title}`} />
        </div>
      ) : null}
    </Link>
  );
}
