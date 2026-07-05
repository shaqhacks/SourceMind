"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";

import ContinueCard from "@/components/dashboard/ContinueCard";
import CourseCard from "@/components/dashboard/CourseCard";
import ErrorBanner from "@/components/ErrorBanner";
import UploadFlow from "@/components/upload/UploadFlow";
import { listCourses, type CourseOut } from "@/lib/api/client";
import { pickMostRecentCourse } from "@/lib/dashboard/continue";

interface FetchError {
  status?: number;
  message: string;
}

function describeError(status: number | undefined, action: string): FetchError {
  if (status === undefined) {
    return { message: `${action}: could not reach the API. Is the backend running?` };
  }
  return { status, message: `${action} failed (HTTP ${status}).` };
}

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
}

export default function Home() {
  const [courses, setCourses] = useState<CourseOut[]>([]);
  const [coursesError, setCoursesError] = useState<FetchError | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[] | null>(null);
  const dragDepth = useRef(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
  const isEmpty = loaded && !coursesError && courses.length === 0;

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
        <h1 className="text-lg font-semibold">Your courses</h1>
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

      {isEmpty ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border p-12 text-center text-muted-foreground">
          <p className="text-lg font-medium">Drop a PDF anywhere to start</p>
          <p className="text-sm">Or use the Upload PDF button above.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-6">
          {continueCourse && <ContinueCard course={continueCourse} />}

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
