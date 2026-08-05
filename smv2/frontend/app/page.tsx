"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";

import CourseCard from "@/components/dashboard/CourseCard";
import SkillSnapshotCard from "@/components/dashboard/SkillSnapshotCard";
import ThisWeekCard from "@/components/dashboard/ThisWeekCard";
import TodayTaskList from "@/components/dashboard/TodayTaskList";
import ErrorBanner from "@/components/ErrorBanner";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import EmptyState from "@/components/ui/EmptyState";
import Skeleton from "@/components/ui/Skeleton";
import UploadFlow from "@/components/upload/UploadFlow";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  getReviewSummary,
  getStudyNext,
  listCourses,
  type CourseOut,
  type ReviewSummaryOut,
  type StudyNextItemOut,
} from "@/lib/api/client";
import { pickMostRecentCourse } from "@/lib/dashboard/continue";
import { buildTaskCards } from "@/lib/dashboard/taskCards";
import { useContinueChapter } from "@/lib/dashboard/useContinueChapter";
import { useRouteFocus } from "@/lib/hooks/useRouteFocus";

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

const DATE_FORMAT: Intl.DateTimeFormatOptions = {
  weekday: "long",
  month: "long",
  day: "numeric",
};

// A lightweight, stated estimate (~30s/card) — not a real timing signal —
// so the "~N min planned" line has something to say without inventing a
// number the way a per-day study-history figure would.
const MINUTES_PER_CARD = 0.5;

function courseOverdueCount(course: ReviewSummaryOut["courses"][number] | undefined): number {
  return course?.overdue_count ?? 0;
}

function totalOverdueCount(summary: ReviewSummaryOut | null): number {
  return summary?.courses.reduce((total, course) => total + courseOverdueCount(course), 0) ?? 0;
}

export default function Home() {
  const [courses, setCourses] = useState<CourseOut[]>([]);
  const [coursesError, setCoursesError] = useState<FetchError | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [reviewSummary, setReviewSummary] = useState<ReviewSummaryOut | null>(null);
  // Tagged with the course id it was fetched for (the useJobEvents idiom)
  // so a course switch derives an empty list during render instead of a
  // synchronous setState-reset in the effect below.
  const [studyNextState, setStudyNextState] = useState<{
    courseId: string;
    items: StudyNextItemOut[];
  } | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[] | null>(null);
  const dragDepth = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useRouteFocus(headingRef);

  const loadCourses = useCallback(async () => {
    const { data, status } = await listCourses();
    if (data) {
      setCourses(data);
      setCoursesError(null);
    } else {
      setCoursesError(describeError(status, "Loading courses"));
    }
  }, []);

  // Mount-only fetch: setState happens inside the .then() callback rather
  // than through loadCourses directly, so an unmount during the in-flight
  // request can't set state on a gone component.
  useEffect(() => {
    let active = true;
    listCourses().then(({ data, status }) => {
      if (!active) return;
      if (data) {
        setCourses(data);
        setCoursesError(null);
      } else {
        setCoursesError(describeError(status, "Loading courses"));
      }
      setLoaded(true);
    });
    return () => {
      active = false;
    };
  }, []);

  // The Review card is a "nice to have" nudge, not core dashboard data —
  // a failure here just means the card doesn't show, no error banner.
  useEffect(() => {
    let active = true;
    getReviewSummary().then(({ data }) => {
      if (active && data) setReviewSummary(data);
    });
    return () => {
      active = false;
    };
  }, []);

  const handleDeleted = useCallback((courseId: string) => {
    setCourses((prev) => prev.filter((course) => course.id !== courseId));
  }, []);

  function handleFilesChosen(files: FileList | File[]) {
    const pdfs = Array.from(files).filter(isPdf);
    if (pdfs.length > 0) setPendingFiles(pdfs);
  }

  function handleDragEnter(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepth.current += 1;
    if (event.dataTransfer.types.includes("Files")) setDragActive(true);
  }

  function handleDragLeave(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepth.current -= 1;
    if (dragDepth.current <= 0) {
      dragDepth.current = 0;
      setDragActive(false);
    }
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    dragDepth.current = 0;
    setDragActive(false);
    handleFilesChosen(event.dataTransfer.files);
  }

  const continueCourse = pickMostRecentCourse(courses);
  // The resume-point chapter (title + percent) for the primary course,
  // shared with the continue-reading task card so its meta text and
  // progress bar can't disagree with each other.
  const continueChapter = useContinueChapter(continueCourse);

  // study_next is scoped to whichever course is the day's primary one —
  // it only ever backs the "retake test" task card (see taskCards.ts).
  // Depend on the id, not the continueCourse object: pickMostRecentCourse
  // recomputes a fresh object every render even when the underlying course
  // hasn't changed (same footgun useContinueChapter.ts documents).
  const continueCourseId = continueCourse?.id ?? null;
  useEffect(() => {
    if (!continueCourseId) return undefined;
    let active = true;
    getStudyNext(continueCourseId).then(({ data }) => {
      if (active && data) setStudyNextState({ courseId: continueCourseId, items: data });
    });
    return () => {
      active = false;
    };
  }, [continueCourseId]);
  const studyNext =
    studyNextState && studyNextState.courseId === continueCourseId
      ? studyNextState.items
      : [];

  // Honest about what one click actually delivers: overdue cards (cross-course)
  // only gates whether a review card shows at all; the count shown and the
  // session it links to are scoped to continueCourse specifically (the
  // same course the continue-reading task card is about), falling back to
  // the generic hub when there's no course to scope a direct session link to.
  const continueCourseOverdueCount = continueCourse
    ? courseOverdueCount(reviewSummary?.courses.find((c) => c.course_id === continueCourse.id))
    : 0;
  const overdueTotal = totalOverdueCount(reviewSummary);
  const showReviewCard = overdueTotal > 0;
  const reviewCardHref =
    continueCourse && continueCourseOverdueCount > 0
      ? `/review?course=${continueCourse.id}&start=due`
      : "/review";
  const reviewCardOverdueCount =
    continueCourseOverdueCount > 0 ? continueCourseOverdueCount : overdueTotal;

  const taskCards = buildTaskCards({
    continueCourse,
    continueChapter,
    showReviewCard,
    reviewCardOverdueCount,
    reviewCardHref,
    studyNext,
  });

  const minutesPlanned =
    overdueTotal > 0 ? Math.max(1, Math.round(overdueTotal * MINUTES_PER_CARD)) : null;
  const skillSnapshotCourseId = continueCourse?.id ?? courses[0]?.id ?? null;

  const isEmpty = loaded && !coursesError && courses.length === 0;

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className="relative mx-auto flex w-full max-w-5xl flex-1 flex-col gap-6 px-6 py-8"
    >
      {dragActive && (
        <div
          role="presentation"
          className="pointer-events-none fixed inset-0 z-40 flex items-center justify-center bg-accent/10"
        >
          <p className="rounded-md bg-background px-6 py-4 text-lg font-medium shadow-lg">
            Drop to upload
          </p>
        </div>
      )}

      <div className="flex items-start justify-between gap-4">
        <div>
          {!isEmpty && (
            <p className="mb-1 text-sm text-muted-foreground">
              {new Date().toLocaleDateString(undefined, DATE_FORMAT)}
              {minutesPlanned != null ? ` · ~${minutesPlanned} min planned` : ""}
            </p>
          )}
          <h1
            ref={headingRef}
            tabIndex={-1}
            className="font-heading text-[34px] outline-none"
          >
            Today&apos;s study plan
          </h1>
        </div>
        <div className="flex items-center gap-6">
          {!isEmpty && (
            <div className="flex gap-5 text-right">
              <div>
                <p className="font-heading text-2xl">
                  {continueChapter ? `${continueChapter.percent}%` : "—"}
                </p>
                <p className="text-xs text-muted-foreground">course progress</p>
              </div>
              <div>
                <p className="font-heading text-2xl">{overdueTotal}</p>
                <p className="text-xs text-muted-foreground">
                  {overdueTotal === 1 ? "card due" : "cards due"}
                </p>
                {reviewSummary?.backlog_warning && (
                  <Badge tone="warning">Backlog</Badge>
                )}
              </div>
              <div>
                <p className="font-heading text-2xl">
                  {Math.round(reviewSummary?.daily_throughput ?? 0)}
                </p>
                <p className="text-xs text-muted-foreground">cards/day (7d avg)</p>
              </div>
            </div>
          )}
          {/* Not in the mock (the sidebar's "+ Start new course" is the
              designed entry point) — kept as a secondary trigger even though
              the app sidebar's "+ Start new course" action now opens the
              dialog itself: the dashboard's empty state points here, and
              drag-drop onto the page still routes through this state. */}
          <div>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/pdf"
              multiple
              className="hidden"
              aria-label="Start a new course"
              onChange={(event) => {
                if (event.target.files) handleFilesChosen(event.target.files);
                event.target.value = "";
              }}
            />
            <Button variant="secondary" onClick={() => fileInputRef.current?.click()}>
              Start a new course
            </Button>
          </div>
        </div>
      </div>

      {coursesError && (
        <ErrorBanner
          status={coursesError.status}
          message={coursesError.message}
          onRetry={loadCourses}
        />
      )}

      {!loaded ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
          <Skeleton className="h-24" />
        </div>
      ) : isEmpty ? (
        <EmptyState
          icon="📚"
          title="Drop a PDF anywhere to start"
          body="Or use the Start a new course button above."
        />
      ) : (
        <div className="flex flex-col gap-8">
          <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[1fr_340px]">
            <TodayTaskList items={taskCards} />
            <div className="flex flex-col gap-4">
              {skillSnapshotCourseId && <SkillSnapshotCard courseId={skillSnapshotCourseId} />}
              <ThisWeekCard />
            </div>
          </div>

          {/* Not in the mock — the redesign replaces this grid with the
              sidebar's own course list, but the sidebar (components/AppSidebar.tsx,
              out of scope here) has no delete/retry-ingest/export affordances or
              per-asset failure detail. Dropping this grid would remove those
              capabilities from the UI entirely with no replacement, so it's kept
              as a "Your courses" section below the plan. */}
          <div className="flex flex-col gap-3">
            <h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
              Your courses
            </h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {courses.map((course) => (
                <CourseCard
                  key={course.id}
                  course={course}
                  onDeleted={handleDeleted}
                  onNeedsRefresh={loadCourses}
                />
              ))}
            </div>
          </div>
        </div>
      )}

      {pendingFiles && (
        <UploadFlow
          files={pendingFiles}
          onClose={() => {
            setPendingFiles(null);
            void loadCourses();
          }}
        />
      )}
    </div>
  );
}
