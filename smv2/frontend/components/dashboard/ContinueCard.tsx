"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { listSections, type CourseOut } from "@/lib/api/client";
import { percentComplete } from "@/lib/dashboard/continue";

export interface ContinueCardProps {
  course: CourseOut;
}

interface ChapterInfo {
  title: string;
  percent: number;
}

/**
 * The dashboard's first-priority card: jump straight back into the most
 * recently read course, at its resume point. Needs one extra
 * list_sections call (not carried on CourseOut) to turn the saved
 * section_id into a chapter title + position-among-content-sections
 * percentage.
 */
export default function ContinueCard({ course }: ContinueCardProps) {
  const [chapter, setChapter] = useState<ChapterInfo | null>(null);
  const sectionId = course.progress?.section_id ?? null;

  useEffect(() => {
    if (!sectionId) return;
    let active = true;
    listSections(course.id).then(({ data }) => {
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
  }, [course.id, sectionId]);

  return (
    <Link
      href={`/course/${course.id}`}
      className="block rounded-lg border border-border bg-accent/5 p-4 transition-colors hover:bg-accent/10"
    >
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Continue reading
      </p>
      <h2 className="mt-1 text-lg font-semibold">{course.title}</h2>
      {chapter ? (
        <p className="mt-1 text-sm text-muted-foreground">
          {chapter.title} — {chapter.percent}% complete
        </p>
      ) : null}
    </Link>
  );
}
