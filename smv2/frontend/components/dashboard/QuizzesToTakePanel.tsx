"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import ErrorBanner from "@/components/ErrorBanner";
import Badge from "@/components/ui/Badge";
import Card from "@/components/ui/Card";
import Skeleton from "@/components/ui/Skeleton";
import { describeError, type FetchError } from "@/lib/api/errors";
import { listChapters, type CourseOut } from "@/lib/api/client";
import { deriveQuizItems, type QuizItem } from "@/lib/dashboard/quizzes";

const COURSE_CAP = 6;
const ITEM_CAP = 5;

export interface QuizzesToTakePanelProps {
  courses: CourseOut[];
  onCount?: (count: number) => void;
}

export default function QuizzesToTakePanel({ courses, onCount }: QuizzesToTakePanelProps) {
  const [items, setItems] = useState<QuizItem[] | null>(null);
  const [error, setError] = useState<FetchError | null>(null);

  const load = useCallback(() => {
    let active = true;
    const targets = courses
      .filter((c) => c.status === "ready")
      .sort((a, b) => {
        const ta = a.progress?.updated_at ? Date.parse(a.progress.updated_at) : 0;
        const tb = b.progress?.updated_at ? Date.parse(b.progress.updated_at) : 0;
        return tb - ta;
      })
      .slice(0, COURSE_CAP);
    Promise.all(
      targets.map(async (course) => {
        const { data, ok, status } = await listChapters(course.id);
        return { courseId: course.id, courseTitle: course.title, chapters: data ?? [], ok, status };
      }),
    ).then((entries) => {
      if (!active) return;
      // The generated client never rejects — a failed request comes back as
      // ok:false with data:undefined, which is indistinguishable from "this
      // course simply has no chapters" unless checked explicitly. Treating
      // that as empty would make a degraded backend read as "0 quizzes due"
      // (a wrong, confident number) instead of a visible, retryable error.
      const failed = entries.find((entry) => !entry.ok);
      if (failed) {
        setError(describeError(failed.status, "Loading quizzes"));
        return;
      }
      setError(null);
      const derived = deriveQuizItems(entries);
      setItems(derived);
      onCount?.(derived.length);
    });
    return () => {
      active = false;
    };
  }, [courses, onCount]);

  useEffect(() => load(), [load]);

  if (error) {
    return (
      <section id="quizzes" aria-label="Quizzes to take" className="flex flex-col gap-3">
        <ErrorBanner status={error.status} message={error.message} onRetry={load} />
      </section>
    );
  }

  if (items === null) {
    return (
      <section id="quizzes" aria-label="Quizzes to take" className="flex flex-col gap-2">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-16 w-full" />
      </section>
    );
  }
  if (items.length === 0) return null; // quiet panel: nothing to nag about

  return (
    <section id="quizzes" aria-labelledby="quizzes-heading" className="flex flex-col gap-3">
      <h2 id="quizzes-heading" className="text-sm font-semibold">
        Quizzes to take
      </h2>
      <ul className="flex flex-col gap-2">
        {items.slice(0, ITEM_CAP).map((item) => (
          <li key={`${item.courseId}:${item.chapterLabel}`}>
            <Link
              href={`/course/${item.courseId}/chapter/${encodeURIComponent(item.chapterLabel)}/test`}
            >
              <Card interactive className="flex items-center justify-between gap-3 py-3">
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">{item.chapterTitle}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {item.courseTitle}
                  </span>
                </span>
                {item.reason === "not_attempted" ? (
                  <Badge tone="accent">Not attempted</Badge>
                ) : (
                  <Badge tone="warning">
                    Retake · best {Math.round((item.bestScore ?? 0) * 100)}%
                  </Badge>
                )}
              </Card>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
