"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import ErrorBanner from "@/components/ErrorBanner";
import JobGroup from "@/components/jobs/JobGroup";
import { describeError, type FetchError } from "@/lib/api/errors";
import { listJobs, retryJob, TERMINAL_JOB_STATUSES, type JobOut } from "@/lib/api/client";

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "ready"; jobs: JobOut[] };

function payloadCourseId(job: JobOut): string {
  return job.payload && typeof job.payload.course_id === "string" ? job.payload.course_id : "unknown course";
}

function groupJobs(jobs: JobOut[]): Map<string, Map<string, JobOut[]>> {
  const grouped = new Map<string, Map<string, JobOut[]>>();
  for (const job of jobs) {
    const courseId = payloadCourseId(job);
    const byType = grouped.get(courseId) ?? new Map<string, JobOut[]>();
    byType.set(job.type, [...(byType.get(job.type) ?? []), job]);
    grouped.set(courseId, byType);
  }
  return grouped;
}

export default function JobsClient() {
  const highlightedJobId = useSearchParams().get("job");
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [actionError, setActionError] = useState<string | null>(null);

  const load = useCallback(() => {
    listJobs().then(({ data, status }) => {
      if (data) setState({ kind: "ready", jobs: data });
      else setState({ kind: "error", error: describeError(status, "Loading jobs") });
    });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleRetry(jobId: string) {
    setActionError(null);
    const result = await retryJob(jobId);
    if (!result.ok) {
      setActionError(describeError(result.status, "Retrying job").message);
      return;
    }
    load();
  }

  const grouped = useMemo(
    () => (state.kind === "ready" ? groupJobs(state.jobs) : new Map<string, Map<string, JobOut[]>>()),
    [state],
  );
  const activeCount = state.kind === "ready" ? state.jobs.filter((job) => !TERMINAL_JOB_STATUSES.has(job.status)).length : 0;

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6 p-6">
      <div>
        <h1 className="font-heading text-3xl">Jobs</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {activeCount} active job{activeCount === 1 ? "" : "s"} in the latest queue.
        </p>
      </div>
      {actionError && <ErrorBanner message={actionError} onRetry={load} />}
      {state.kind === "loading" && <p role="status">Loading jobs...</p>}
      {state.kind === "error" && (
        <ErrorBanner status={state.error.status} message={state.error.message} onRetry={load} />
      )}
      {state.kind === "ready" && state.jobs.length === 0 && (
        <p className="text-sm text-muted-foreground">No jobs yet.</p>
      )}
      {state.kind === "ready" &&
        Array.from(grouped.entries()).map(([courseId, byType]) => (
          <section key={courseId} className="flex flex-col gap-4">
            <h2 className="font-heading text-xl">Course {courseId}</h2>
            {Array.from(byType.entries()).map(([type, jobs]) => (
              <JobGroup
                key={type}
                courseId={courseId}
                type={type}
                jobs={jobs}
                highlightedJobId={highlightedJobId}
                onRetry={handleRetry}
              />
            ))}
          </section>
        ))}
    </div>
  );
}
