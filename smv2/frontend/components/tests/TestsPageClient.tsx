"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import ErrorBanner from "@/components/ErrorBanner";
import EmptyState from "@/components/ui/EmptyState";
import Skeleton from "@/components/ui/Skeleton";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  listChapters,
  listCourses,
  listTests,
  type ChapterOut,
  type CourseOut,
  type TestSummaryOut,
} from "@/lib/api/client";
import { useRouteFocus } from "@/lib/hooks/useRouteFocus";

import ChapterTestCard from "./ChapterTestCard";
import DiagnosisCard from "./DiagnosisCard";
import GenerateTestCard from "./GenerateTestCard";
import ScoreHistoryCard from "./ScoreHistoryCard";

type CoursesState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "ready"; courses: CourseOut[] };

type ChaptersState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "ready"; chapters: ChapterOut[]; tests: TestSummaryOut[] };

export default function TestsPageClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const courseParam = searchParams.get("course");
  const headingRef = useRef<HTMLHeadingElement>(null);
  useRouteFocus(headingRef);

  const [coursesState, setCoursesState] = useState<CoursesState>({ kind: "loading" });
  const [chaptersState, setChaptersState] = useState<ChaptersState>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    listCourses().then(({ data, status }) => {
      if (!active) return;
      if (data) setCoursesState({ kind: "ready", courses: data });
      else setCoursesState({ kind: "error", error: describeError(status, "Loading courses") });
    });
    return () => {
      active = false;
    };
  }, []);

  const readyCourses =
    coursesState.kind === "ready" ? coursesState.courses.filter((c) => c.status === "ready") : [];
  const selectedCourseId = courseParam ?? readyCourses[0]?.id ?? null;

  // Deliberately doesn't reset to "loading" before (re)fetching — same
  // idiom as QuizzesPanel's loadTests: every setState here stays inside
  // the .then(), so this is safe to call directly from an effect body
  // (a synchronous setState at the top of an effect schedules an extra
  // render every dependency change). Switching courses or retrying after
  // an error just quietly replaces the state once the fetch resolves,
  // rather than flashing back through a loading skeleton.
  const loadChapters = useCallback((courseId: string) => {
    Promise.all([listChapters(courseId), listTests(courseId)]).then(
      ([chaptersResult, testsResult]) => {
        if (!chaptersResult.data) {
          setChaptersState({
            kind: "error",
            error: describeError(chaptersResult.status, "Loading chapters"),
          });
          return;
        }
        if (!testsResult.data) {
          setChaptersState({
            kind: "error",
            error: describeError(testsResult.status, "Loading tests"),
          });
          return;
        }
        setChaptersState({ kind: "ready", chapters: chaptersResult.data, tests: testsResult.data });
      },
    );
  }, []);

  useEffect(() => {
    if (selectedCourseId) loadChapters(selectedCourseId);
  }, [selectedCourseId, loadChapters]);

  function selectCourse(id: string) {
    router.push(`/tests?course=${id}`);
  }

  let body: React.ReactNode;

  if (coursesState.kind === "loading") {
    body = (
      <div role="status" className="flex flex-col gap-3">
        <span className="sr-only">Loading…</span>
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  } else if (coursesState.kind === "error") {
    body = (
      <ErrorBanner
        status={coursesState.error.status}
        message={coursesState.error.message}
        onRetry={() => {
          setCoursesState({ kind: "loading" });
          listCourses().then(({ data, status }) => {
            if (data) setCoursesState({ kind: "ready", courses: data });
            else setCoursesState({ kind: "error", error: describeError(status, "Loading courses") });
          });
        }}
      />
    );
  } else if (readyCourses.length === 0) {
    body = (
      <EmptyState
        icon="📝"
        title="No courses ready yet"
        body="Finish uploading a course to generate and take chapter tests."
      />
    );
  } else if (!selectedCourseId) {
    body = null;
  } else if (chaptersState.kind === "loading") {
    body = (
      <div role="status" className="flex flex-col gap-3">
        <span className="sr-only">Loading…</span>
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  } else if (chaptersState.kind === "error") {
    body = (
      <ErrorBanner
        status={chaptersState.error.status}
        message={chaptersState.error.message}
        onRetry={() => loadChapters(selectedCourseId)}
      />
    );
  } else {
    const { chapters, tests } = chaptersState;
    // Front matter (chapter_label: null) has nothing to link or test —
    // same precedent as lib/dashboard/quizzes.ts.
    const namedChapters = chapters.filter(
      (chapter): chapter is ChapterOut & { chapter_label: string } => chapter.chapter_label !== null,
    );

    if (namedChapters.length === 0) {
      body = (
        <EmptyState icon="📝" title="No chapters yet" body="This course has no chapters to test." />
      );
    } else {
      body = (
        <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[1fr_340px]">
          <div className="flex flex-col gap-3.5">
            {namedChapters.map((chapter) => {
              const label = chapter.chapter_label;
              const stats = chapter.test_stats;
              const hasAttempts = stats !== null && stats.attempts > 0 && stats.best_score !== null;
              return hasAttempts ? (
                <ChapterTestCard
                  key={label}
                  courseId={selectedCourseId}
                  chapterLabel={label}
                  tests={tests}
                  attempts={stats.attempts}
                  bestScore={stats.best_score as number}
                />
              ) : (
                <GenerateTestCard
                  key={label}
                  courseId={selectedCourseId}
                  chapterLabel={label}
                  existingTests={tests.filter((test) => test.chapter_label === label)}
                  onSettled={() => loadChapters(selectedCourseId)}
                />
              );
            })}
          </div>
          <div className="flex flex-col gap-4">
            <ScoreHistoryCard tests={tests} />
            <DiagnosisCard courseId={selectedCourseId} />
          </div>
        </div>
      );
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-[1060px] flex-col gap-6 px-9 py-8">
      <div>
        <h1 ref={headingRef} tabIndex={-1} className="font-heading text-[34px] outline-none">
          Tests
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Chapter tests are generated from your course · retakes reuse the same questions, free
        </p>
      </div>
      {readyCourses.length > 1 && (
        <label className="flex items-center gap-2 text-sm">
          <span className="font-medium">Course</span>
          <select
            value={selectedCourseId ?? ""}
            onChange={(event) => selectCourse(event.target.value)}
            className="rounded-md border border-border bg-surface-raised px-2 py-1.5"
          >
            {readyCourses.map((course) => (
              <option key={course.id} value={course.id}>
                {course.title}
              </option>
            ))}
          </select>
        </label>
      )}
      {body}
    </div>
  );
}
