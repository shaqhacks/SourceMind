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

// error/ready are tagged with the courseId they were fetched for. Two
// defenses key off this tag: loadChapters below skips WRITING a response
// whose courseId no longer matches the current selection (a stale fetch
// that resolved after the user switched courses), and
// displayedChaptersState further down re-checks the tag at render time as
// defense in depth. Same two-layer shape as FlashcardsClient's
// selectedCourseIdRef write-guard plus its CourseDataEntry render-time
// check.
type ChaptersState =
  | { kind: "loading" }
  | { kind: "error"; courseId: string; error: FetchError }
  | { kind: "ready"; courseId: string; chapters: ChapterOut[]; tests: TestSummaryOut[] };

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

  // Mirrors selectedCourseId for loadChapters' resolve-time staleness check
  // below — a ref, not the selectedCourseId variable itself, because
  // loadChapters (and the .then() closure it creates) is called from a
  // specific render and would otherwise only ever see that render's own
  // selectedCourseId (which always equals the courseId argument, defeating
  // the check). Declared — and synced — before the fetch-triggering effect
  // further down so that effect's first run already has a ref in place.
  const selectedCourseIdRef = useRef<string | null>(selectedCourseId);
  useEffect(() => {
    selectedCourseIdRef.current = selectedCourseId;
  }, [selectedCourseId]);

  // Deliberately doesn't reset to "loading" before (re)fetching — same
  // idiom as QuizzesPanel's loadTests: every setState here stays inside
  // the .then(), so this is safe to call directly from an effect body
  // (a synchronous setState at the top of an effect schedules an extra
  // render every dependency change). Switching courses or retrying after
  // an error just quietly replaces the state once the fetch resolves,
  // rather than flashing back through a loading skeleton.
  //
  // Every write below is guarded against staleness: rapid course switching
  // (A -> B -> C) can let A's fetch resolve last, after C's has already
  // landed. Without the guard that stale write would overwrite C's good
  // entry with one tagged courseId: "A", which displayedChaptersState's
  // render-time mask would then hide as "loading" forever — the mask has
  // no retry of its own, and the fetch effect below only re-runs when
  // selectedCourseId itself changes again. So the write itself checks the
  // current selection (via selectedCourseIdRef, per the comment above) and
  // skips silently for an abandoned course instead of clobbering a newer
  // entry — same pattern as FlashcardsClient's reloadCourseData.
  const loadChapters = useCallback((courseId: string) => {
    Promise.all([listChapters(courseId), listTests(courseId)]).then(
      ([chaptersResult, testsResult]) => {
        if (!chaptersResult.data) {
          const error = describeError(chaptersResult.status, "Loading chapters");
          setChaptersState((current) =>
            courseId === selectedCourseIdRef.current ? { kind: "error", courseId, error } : current,
          );
          return;
        }
        if (!testsResult.data) {
          const error = describeError(testsResult.status, "Loading tests");
          setChaptersState((current) =>
            courseId === selectedCourseIdRef.current ? { kind: "error", courseId, error } : current,
          );
          return;
        }
        // Destructured into their own const bindings (rather than referenced
        // as chaptersResult.data / testsResult.data below) so the `!data`
        // narrowing above survives into the setState updater closure — TS
        // does not carry a property-access narrowing across a function
        // boundary, only a local const's.
        const chapters = chaptersResult.data;
        const tests = testsResult.data;
        setChaptersState((current) =>
          courseId === selectedCourseIdRef.current
            ? { kind: "ready", courseId, chapters, tests }
            : current,
        );
      },
    );
  }, []);

  useEffect(() => {
    if (selectedCourseId) loadChapters(selectedCourseId);
  }, [selectedCourseId, loadChapters]);

  // A response tagged with a courseId that no longer matches the current
  // selection is a stale fetch that resolved after the user switched courses
  // — render it as still-loading (the switch's own fetch is in flight)
  // rather than flashing the abandoned course's chapters/tests.
  const displayedChaptersState: ChaptersState =
    chaptersState.kind !== "loading" && chaptersState.courseId !== selectedCourseId
      ? { kind: "loading" }
      : chaptersState;

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
  } else if (displayedChaptersState.kind === "loading") {
    body = (
      <div role="status" className="flex flex-col gap-3">
        <span className="sr-only">Loading…</span>
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  } else if (displayedChaptersState.kind === "error") {
    body = (
      <ErrorBanner
        status={displayedChaptersState.error.status}
        message={displayedChaptersState.error.message}
        onRetry={() => loadChapters(selectedCourseId)}
      />
    );
  } else {
    const { chapters, tests } = displayedChaptersState;
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
                  key={`${selectedCourseId}-${label}`}
                  courseId={selectedCourseId}
                  chapterLabel={label}
                  tests={tests}
                  attempts={stats.attempts}
                  bestScore={stats.best_score as number}
                />
              ) : (
                <GenerateTestCard
                  key={`${selectedCourseId}-${label}`}
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
