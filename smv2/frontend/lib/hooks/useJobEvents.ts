"use client";

import { useEffect, useState } from "react";

import { API_BASE } from "@/lib/api/client";

export interface JobProgress {
  stage: string;
  pct: number;
  message: string;
}

export interface JobEvent {
  id: string;
  status: string;
  progress: JobProgress | null;
}

export interface UseJobEventsResult {
  job: JobEvent | null;
  error: string | null;
  done: boolean;
}

interface StreamState {
  jobId: string | null;
  job: JobEvent | null;
  error: string | null;
  done: boolean;
}

const EMPTY_RESULT: UseJobEventsResult = { job: null, error: null, done: false };
const TERMINAL_STATUSES = new Set(["succeeded", "failed"]);

/**
 * THE shared SSE hook (brief law: one shared SSE hook, no client polling
 * anywhere). EventSource has no openapi-fetch equivalent, so — unlike every
 * other request in this app — this hook talks to the API directly via
 * API_BASE rather than through lib/api/client.ts. That's the one sanctioned
 * exception to the single-fetch-boundary rule.
 *
 * Connects to GET /api/jobs/{jobId}/events, applies `update` events, and
 * closes the stream on a terminal status (succeeded/failed), on unmount, or
 * on a connection error. Never reconnects automatically — a dropped stream
 * surfaces as `error` and stays closed; callers needing recovery should
 * fall back to a one-shot REST fetch (see app/page.tsx), not a retry loop.
 */
export function useJobEvents(jobId: string | null): UseJobEventsResult {
  // State is tagged with the jobId it belongs to. When jobId changes, the
  // effect below doesn't reset state itself (a bare setState at the top of
  // an effect, with no async boundary, has no honest home in a callback);
  // instead the stale-tag check below derives "no data yet for this job"
  // during render, same as React's own guidance for state that depends on
  // a changing prop.
  const [state, setState] = useState<StreamState>({
    jobId: null,
    job: null,
    error: null,
    done: false,
  });

  useEffect(() => {
    if (!jobId) {
      return;
    }

    const source = new EventSource(`${API_BASE}/api/jobs/${jobId}/events`);

    source.addEventListener("update", (event) => {
      try {
        const parsed = JSON.parse((event as MessageEvent<string>).data) as JobEvent;
        const done = TERMINAL_STATUSES.has(parsed.status);
        setState({ jobId, job: parsed, error: null, done });
        if (done) {
          source.close();
        }
      } catch {
        setState((prev) => ({
          jobId,
          job: prev.jobId === jobId ? prev.job : null,
          error: "Received a malformed update from the job stream.",
          done: false,
        }));
        source.close();
      }
    });

    source.onerror = () => {
      setState((prev) => ({
        jobId,
        job: prev.jobId === jobId ? prev.job : null,
        error: "Lost connection to the job stream.",
        done: false,
      }));
      source.close();
    };

    return () => {
      source.close();
    };
  }, [jobId]);

  if (state.jobId !== jobId) {
    return EMPTY_RESULT;
  }
  return { job: state.job, error: state.error, done: state.done };
}
