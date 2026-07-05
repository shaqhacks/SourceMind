"use client";

import { type FormEvent, useCallback, useEffect, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import {
  createCourse,
  createJob,
  deleteCourse,
  getHealth,
  getJob,
  listCourses,
  listJobs,
  type CourseOut,
  type JobOut,
} from "@/lib/api/client";
import { useJobEvents, type JobProgress } from "@/lib/hooks/useJobEvents";

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

// JobOut.progress is a loosely-typed `{[key: string]: unknown} | null` in the
// generated schema (the backend column is a generic JSON dict); narrow it to
// the {stage, pct, message} shape the worker actually writes before
// rendering it, rather than trusting an unchecked cast.
function asJobProgress(value: { [key: string]: unknown } | null | undefined): JobProgress | null {
  if (
    value &&
    typeof value.stage === "string" &&
    typeof value.pct === "number" &&
    typeof value.message === "string"
  ) {
    return { stage: value.stage, pct: value.pct, message: value.message };
  }
  return null;
}

type HealthState =
  | { kind: "loading" }
  | { kind: "ok"; version: string }
  | { kind: "error"; error: FetchError };

export default function Home() {
  const [health, setHealth] = useState<HealthState>({ kind: "loading" });
  const [jobs, setJobs] = useState<JobOut[]>([]);
  const [jobsError, setJobsError] = useState<FetchError | null>(null);
  const [currentJob, setCurrentJob] = useState<JobOut | null>(null);
  const [jobError, setJobError] = useState<FetchError | null>(null);
  const [creating, setCreating] = useState(false);

  const [courses, setCourses] = useState<CourseOut[]>([]);
  const [coursesError, setCoursesError] = useState<FetchError | null>(null);
  const [courseTitle, setCourseTitle] = useState("");
  const [creatingCourse, setCreatingCourse] = useState(false);
  const [deletingCourseId, setDeletingCourseId] = useState<string | null>(null);

  const currentJobId = currentJob?.id ?? null;
  const { job: liveJob, error: sseError, done: jobDone } = useJobEvents(currentJobId);

  const loadHealth = useCallback(async () => {
    const { data, status } = await getHealth();
    if (data) {
      setHealth({ kind: "ok", version: data.version ?? "unknown" });
    } else {
      setHealth({ kind: "error", error: describeError(status, "Health check") });
    }
  }, []);

  const loadJobs = useCallback(async () => {
    const { data, status } = await listJobs();
    if (data) {
      setJobs(data);
      setJobsError(null);
    } else {
      setJobsError(describeError(status, "Loading jobs"));
    }
  }, []);

  const loadCourses = useCallback(async () => {
    const { data, status } = await listCourses();
    if (data) {
      setCourses(data);
      setCoursesError(null);
    } else {
      setCoursesError(describeError(status, "Loading courses"));
    }
  }, []);

  const runNoopJob = useCallback(async () => {
    setCreating(true);
    setJobError(null);
    const { data, status } = await createJob({ type: "noop" });
    setCreating(false);
    if (!data) {
      setJobError(describeError(status, "Creating job"));
      return;
    }
    setCurrentJob(data);
    await loadJobs();
  }, [loadJobs]);

  // The live SSE stream is the source of truth for status/progress once
  // connected; a dropped stream falls back to a single plain GET rather
  // than reconnecting the stream (useJobEvents never auto-retries).
  const refetchJobOnce = useCallback(async () => {
    if (!currentJobId) return;
    const { data, status } = await getJob(currentJobId);
    if (data) {
      setCurrentJob(data);
      setJobError(null);
    } else {
      setJobError(describeError(status, "Refreshing job"));
    }
  }, [currentJobId]);

  const handleCreateCourse = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const title = courseTitle.trim();
      if (!title) return;
      setCreatingCourse(true);
      const { data, status } = await createCourse({ title });
      setCreatingCourse(false);
      if (!data) {
        setCoursesError(describeError(status, "Creating course"));
        return;
      }
      setCourseTitle("");
      await loadCourses();
    },
    [courseTitle, loadCourses],
  );

  const handleDeleteCourse = useCallback(
    async (courseId: string) => {
      setDeletingCourseId(courseId);
      const { ok, status } = await deleteCourse(courseId);
      setDeletingCourseId(null);
      if (!ok) {
        setCoursesError(describeError(status, "Deleting course"));
        return;
      }
      await loadCourses();
    },
    [loadCourses],
  );

  // Once a job reaches a terminal status, the recent-jobs list is stale
  // (still shows the pre-completion status) — refresh it exactly once.
  // Calls listJobs directly and sets state inside .then() (not the shared
  // loadJobs) for the same reason as the mount effect below.
  useEffect(() => {
    if (!jobDone) return;
    let active = true;
    listJobs().then(({ data, status }) => {
      if (!active) return;
      if (data) {
        setJobs(data);
        setJobsError(null);
      } else {
        setJobsError(describeError(status, "Loading jobs"));
      }
    });
    return () => {
      active = false;
    };
  }, [jobDone]);

  // Mount-only fetch: setState happens inside the .then() callback rather
  // than through loadHealth/loadJobs/loadCourses directly, so an unmount
  // during the in-flight request can't set state on a gone component.
  useEffect(() => {
    let active = true;

    getHealth().then(({ data, status }) => {
      if (!active) return;
      setHealth(
        data
          ? { kind: "ok", version: data.version ?? "unknown" }
          : { kind: "error", error: describeError(status, "Health check") },
      );
    });

    listJobs().then(({ data, status }) => {
      if (!active) return;
      if (data) {
        setJobs(data);
        setJobsError(null);
      } else {
        setJobsError(describeError(status, "Loading jobs"));
      }
    });

    listCourses().then(({ data, status }) => {
      if (!active) return;
      if (data) {
        setCourses(data);
        setCoursesError(null);
      } else {
        setCoursesError(describeError(status, "Loading courses"));
      }
    });

    return () => {
      active = false;
    };
  }, []);

  const displayStatus = liveJob?.status ?? currentJob?.status;
  const displayProgress = liveJob?.progress ?? asJobProgress(currentJob?.progress);

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 px-6 py-8">
      <section>
        <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-black/60 dark:text-white/60">
          API status
        </h2>
        {health.kind === "loading" && <p className="text-sm">Checking API…</p>}
        {health.kind === "ok" && (
          <p data-testid="health-ok" className="text-sm">
            API: ok{" "}
            <span className="text-black/50 dark:text-white/50">v{health.version}</span>
          </p>
        )}
        {health.kind === "error" && (
          <ErrorBanner
            status={health.error.status}
            message={health.error.message}
            onRetry={loadHealth}
          />
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium uppercase tracking-wide text-black/60 dark:text-white/60">
          Job demo
        </h2>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={runNoopJob}
            disabled={creating}
            className="rounded-md bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-black"
          >
            {creating ? "Running…" : "Run no-op job"}
          </button>
        </div>

        {jobError && (
          <ErrorBanner
            status={jobError.status}
            message={jobError.message}
            onRetry={currentJob ? refetchJobOnce : runNoopJob}
          />
        )}

        {sseError && !jobDone && (
          <ErrorBanner message={sseError} onRetry={refetchJobOnce} />
        )}

        {currentJob && (
          <div data-testid="current-job" className="text-sm">
            <p>
              Job{" "}
              <code className="rounded bg-black/5 px-1 py-0.5 dark:bg-white/10">
                {currentJob.id}
              </code>
              : <span className="font-medium">{displayStatus}</span>
            </p>
            {displayProgress && (
              <p className="text-xs text-black/60 dark:text-white/60">
                {displayProgress.stage} — {displayProgress.pct}% — {displayProgress.message}
              </p>
            )}
          </div>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium uppercase tracking-wide text-black/60 dark:text-white/60">
          Courses
        </h2>
        <form onSubmit={handleCreateCourse} className="flex items-center gap-3">
          <input
            type="text"
            value={courseTitle}
            onChange={(event) => setCourseTitle(event.target.value)}
            placeholder="Course title"
            aria-label="Course title"
            className="flex-1 rounded-md border border-black/20 bg-transparent px-3 py-2 text-sm dark:border-white/20"
          />
          <button
            type="submit"
            disabled={creatingCourse || !courseTitle.trim()}
            className="rounded-md bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-black"
          >
            {creatingCourse ? "Creating…" : "Create course"}
          </button>
        </form>

        {coursesError && (
          <ErrorBanner
            status={coursesError.status}
            message={coursesError.message}
            onRetry={loadCourses}
          />
        )}

        <div className="max-h-80 overflow-y-auto rounded-md border border-black/10 dark:border-white/10">
          {courses.length === 0 ? (
            <p className="p-4 text-sm text-black/50 dark:text-white/50">No courses yet.</p>
          ) : (
            <ul className="divide-y divide-black/10 dark:divide-white/10">
              {courses.map((course) => (
                <li
                  key={course.id}
                  className="flex items-center justify-between px-4 py-2 text-sm"
                >
                  <span className="truncate">{course.title}</span>
                  <div className="flex shrink-0 items-center gap-3 pl-3">
                    <span className="text-xs text-black/50 dark:text-white/50">
                      {course.status}
                    </span>
                    <button
                      type="button"
                      onClick={() => handleDeleteCourse(course.id)}
                      disabled={deletingCourseId === course.id}
                      className="text-xs font-medium text-red-600 hover:underline disabled:opacity-50 dark:text-red-400"
                    >
                      {deletingCourseId === course.id ? "Deleting…" : "Delete"}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      <section className="flex min-h-0 flex-1 flex-col gap-2">
        <h2 className="text-sm font-medium uppercase tracking-wide text-black/60 dark:text-white/60">
          Recent jobs
        </h2>
        {jobsError && (
          <ErrorBanner status={jobsError.status} message={jobsError.message} onRetry={loadJobs} />
        )}
        <div className="max-h-80 overflow-y-auto rounded-md border border-black/10 dark:border-white/10">
          {jobs.length === 0 ? (
            <p className="p-4 text-sm text-black/50 dark:text-white/50">No jobs yet.</p>
          ) : (
            <ul className="divide-y divide-black/10 dark:divide-white/10">
              {jobs.map((job) => (
                <li key={job.id} className="flex items-center justify-between px-4 py-2 text-sm">
                  <span className="truncate font-mono text-xs">{job.id}</span>
                  <span className="shrink-0 pl-3">{job.status}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}
