"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import {
  createJob,
  getHealth,
  getJob,
  listJobs,
  type JobOut,
} from "@/lib/api/client";

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
  const [refreshing, setRefreshing] = useState(false);
  const refetchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  // Phase 0 has no SSE/polling: a job's status is refetched exactly once,
  // 600ms after creation, plus whenever the user hits Refresh.
  const refreshCurrentJob = useCallback(
    async (jobId: string) => {
      setRefreshing(true);
      const { data, status } = await getJob(jobId);
      setRefreshing(false);
      if (data) {
        setCurrentJob(data);
        setJobError(null);
      } else {
        setJobError(describeError(status, "Refreshing job"));
      }
      await loadJobs();
    },
    [loadJobs],
  );

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

    if (refetchTimeout.current) clearTimeout(refetchTimeout.current);
    refetchTimeout.current = setTimeout(() => {
      void refreshCurrentJob(data.id);
    }, 600);
  }, [loadJobs, refreshCurrentJob]);

  // Mount-only fetch: setState happens inside the .then() callback rather
  // than through loadHealth/loadJobs directly, so an unmount during the
  // in-flight request can't set state on a gone component.
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

    return () => {
      active = false;
      if (refetchTimeout.current) clearTimeout(refetchTimeout.current);
    };
  }, []);

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
          {currentJob && (
            <button
              type="button"
              onClick={() => refreshCurrentJob(currentJob.id)}
              disabled={refreshing}
              className="rounded-md border border-black/20 px-4 py-2 text-sm font-medium disabled:opacity-50 dark:border-white/20"
            >
              {refreshing ? "Refreshing…" : "Refresh"}
            </button>
          )}
        </div>

        {jobError && (
          <ErrorBanner
            status={jobError.status}
            message={jobError.message}
            onRetry={currentJob ? () => refreshCurrentJob(currentJob.id) : runNoopJob}
          />
        )}

        {currentJob && (
          <p data-testid="current-job" className="text-sm">
            Job{" "}
            <code className="rounded bg-black/5 px-1 py-0.5 dark:bg-white/10">
              {currentJob.id}
            </code>
            : <span className="font-medium">{currentJob.status}</span>
          </p>
        )}
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
