"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";

import ContinueCard from "@/components/dashboard/ContinueCard";
import CourseCard from "@/components/dashboard/CourseCard";
import ReviewCard from "@/components/dashboard/ReviewCard";
import StudyNextList from "@/components/dashboard/StudyNextList";
import ErrorBanner from "@/components/ErrorBanner";
import UploadFlow from "@/components/upload/UploadFlow";
import { describeError, type FetchError } from "@/lib/api/errors";
import { getReviewSummary, listCourses, type CourseOut, type ReviewSummaryOut } from "@/lib/api/client";
import { pickMostRecentCourse } from "@/lib/dashboard/continue";
import { useRouteFocus } from "@/lib/hooks/useRouteFocus";
import { useSampleHintDismissed } from "@/lib/hooks/useSampleHint";

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

export default function Home() {
  const [courses, setCourses] = useState<CourseOut[]>([]);
  const [coursesError, setCoursesError] = useState<FetchError | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [reviewSummary, setReviewSummary] = useState<ReviewSummaryOut | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[] | null>(null);
  const dragDepth = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useRouteFocus(headingRef);
  const { dismissed: sampleHintDismissed, dismiss: dismissSampleHint } = useSampleHintDismissed();

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
  // Honest about what one click actually delivers: due_total (cross-course)
  // only gates whether a review card shows at all; the count shown and the
  // session it links to are scoped to continueCourse specifically (the
  // same course ContinueCard is about), falling back to the generic hub
  // when there's no course to scope a direct session link to.
  const continueCourseDueCount = continueCourse
    ? (reviewSummary?.courses.find((c) => c.course_id === continueCourse.id)?.due_count ?? 0)
    : 0;
  const showReviewCard = (reviewSummary?.due_total ?? 0) > 0;
  const reviewCardHref =
    continueCourse && continueCourseDueCount > 0
      ? `/review?course=${continueCourse.id}&start=due`
      : "/review";
  const reviewCardDueCount =
    continueCourseDueCount > 0 ? continueCourseDueCount : (reviewSummary?.due_total ?? 0);
  const isEmpty = loaded && !coursesError && courses.length === 0;
  // The backend seeds a single "Welcome to SourceMind" sample course on
  // first launch — this hint only ever applies to that exact moment (one
  // course, already usable), not to a user's own first upload (which
  // starts as "draft" before ingest even begins).
  const showSampleHint =
    !sampleHintDismissed &&
    courses.length === 1 &&
    (courses[0].status === "ingesting" || courses[0].status === "ready");

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className="relative mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-8"
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

      <div className="flex items-center justify-between">
        <h1 ref={headingRef} tabIndex={-1} className="text-lg font-semibold outline-none">
          Your courses
        </h1>
        <div>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            multiple
            className="hidden"
            aria-label="Upload PDF"
            onChange={(event) => {
              if (event.target.files) handleFilesChosen(event.target.files);
              event.target.value = "";
            }}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="rounded-md bg-black px-4 py-2 text-sm font-medium text-white dark:bg-white dark:text-black"
          >
            Upload PDF
          </button>
        </div>
      </div>

      {coursesError && (
        <ErrorBanner
          status={coursesError.status}
          message={coursesError.message}
          onRetry={loadCourses}
        />
      )}

      {showSampleHint && (
        <div
          role="note"
          className="flex items-center justify-between gap-3 rounded-md border border-border bg-accent/5 px-4 py-3 text-sm"
        >
          <span>This is a sample course — drop any PDF to create your own.</span>
          <button
            type="button"
            onClick={dismissSampleHint}
            aria-label="Dismiss hint"
            className="shrink-0 rounded-md border border-border px-2 py-1 text-xs font-medium"
          >
            Dismiss
          </button>
        </div>
      )}

      {isEmpty ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-12 text-center text-muted-foreground">
          <p className="text-lg font-medium">Drop a PDF anywhere to start</p>
          <p className="text-sm">Or use the Upload PDF button above.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          {(continueCourse || showReviewCard) && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {continueCourse && <ContinueCard course={continueCourse} />}
              {showReviewCard && (
                <ReviewCard dueCount={reviewCardDueCount} href={reviewCardHref} />
              )}
            </div>
          )}

          {continueCourse && <StudyNextList courseId={continueCourse.id} />}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
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
