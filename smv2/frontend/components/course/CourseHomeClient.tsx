"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Badge from "@/components/ui/Badge";
import Card from "@/components/ui/Card";
import Skeleton from "@/components/ui/Skeleton";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  getCourse,
  getReviewSummary,
  type CourseOut,
} from "@/lib/api/client";
import { useRouteFocus } from "@/lib/hooks/useRouteFocus";

export interface CourseHomeClientProps {
  courseId: string;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "ready"; course: CourseOut; overdueCount: number };

interface NavCard {
  href: string;
  icon: string;
  title: string;
  description: string;
}

function navCards(courseId: string, overdueCount: number): NavCard[] {
  return [
    {
      href: `/course/${courseId}/read`,
      icon: "📖",
      title: "Lessons",
      description: "Read the book and review generated lessons",
    },
    {
      href: `/review?course=${encodeURIComponent(courseId)}&scope=all`,
      icon: "🃏",
      title: "Flashcards",
      description:
        overdueCount > 0
          ? `${overdueCount} card${overdueCount === 1 ? "" : "s"} due to review`
          : "Study flashcards with spaced repetition",
    },
    {
      href: `/course/${courseId}/skills`,
      icon: "🗺️",
      title: "Skill map",
      description: "Explore concepts, claims, and prerequisites",
    },
    {
      href: `/tests?course=${encodeURIComponent(courseId)}`,
      icon: "✅",
      title: "Tests",
      description: "Take and review chapter quizzes",
    },
  ];
}

async function fetchCourseHome(courseId: string): Promise<LoadState> {
  const [courseResult, summaryResult] = await Promise.all([
    getCourse(courseId),
    getReviewSummary(),
  ]);

  if (!courseResult.data) {
    return { kind: "error", error: describeError(courseResult.status, "Loading course") };
  }

  const overdueCount =
    summaryResult.data?.courses.find((c) => c.course_id === courseId)?.overdue_count ?? 0;

  return { kind: "ready", course: courseResult.data, overdueCount };
}

export default function CourseHomeClient({ courseId }: CourseHomeClientProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const headingRef = useRef<HTMLHeadingElement>(null);
  useRouteFocus(headingRef);

  useEffect(() => {
    let active = true;
    fetchCourseHome(courseId).then((next) => {
      if (active) setState(next);
    });
    return () => {
      active = false;
    };
  }, [courseId]);

  const retry = useCallback(() => {
    setState({ kind: "loading" });
    fetchCourseHome(courseId).then(setState);
  }, [courseId]);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-6 py-8">
      {state.kind === "loading" ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-10 w-64" />
          <Skeleton className="h-32" />
        </div>
      ) : state.kind === "error" ? (
        <ErrorBanner
          status={state.error.status}
          message={state.error.message}
          onRetry={retry}
        />
      ) : (
        <>
          <header className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1
                ref={headingRef}
                tabIndex={-1}
                className="font-heading text-[34px] outline-none"
              >
                {state.course.title}
              </h1>
              <p className="mt-1 text-sm text-muted-foreground">
                {state.course.section_count} section
                {state.course.section_count === 1 ? "" : "s"}
              </p>
            </div>
            {state.course.status === "ready" && <Badge tone="good">Ready</Badge>}
          </header>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {navCards(courseId, state.overdueCount).map((card) => (
              <Link key={card.title} href={card.href} className="group block">
                <Card interactive className="h-full">
                  <div className="flex flex-col gap-2">
                    <span aria-hidden="true" className="text-2xl">
                      {card.icon}
                    </span>
                    <h2 className="font-heading text-lg group-hover:text-accent-700">
                      {card.title}
                    </h2>
                    <p className="text-sm text-muted-foreground">{card.description}</p>
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
