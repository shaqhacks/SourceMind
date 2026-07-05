"use client";

import { useEffect, useState } from "react";

import { API_BASE, TERMINAL_JOB_STATUSES } from "@/lib/api/client";

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
  /**
   * True once 120s have passed with no SSE event since the stream opened
   * (or since the last event), and the job hasn't reached a terminal
   * status. Not an error — the async-job UX law wants a "still working"
   * state distinct from a failure, not a dead end or a bare spinner.
   */
  stalled: boolean;
}

interface StreamState {
  jobId: string | null;
  job: JobEvent | null;
  error: string | null;
  done: boolean;
  stalled: boolean;
}

const EMPTY_RESULT: UseJobEventsResult = { job: null, error: null, done: false, stalled: false };
const STALL_TIMEOUT_MS = 120_000;

/**
 * JobOut.progress is a loosely-typed `{[key: string]: unknown} | null` (the
 * backend column is a generic JSON dict); narrow it to the {stage, pct,
 * message} shape the job workers actually write. For callers reading a
 * plain REST response (list_jobs, get_job) rather than the SSE stream,
 * which already produces JobEvent/JobProgress directly.
 */
export function asJobProgress(
  value: { [key: string]: unknown } | null | undefined,
): JobProgress | null {
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
    stalled: false,
  });

  useEffect(() => {
    if (!jobId) {
      return;
    }

    const source = new EventSource(`${API_BASE}/api/jobs/${jobId}/events`);
    let stallTimer: ReturnType<typeof setTimeout> | null = null;

    function clearStallTimer() {
      if (stallTimer !== null) {
        clearTimeout(stallTimer);
        stallTimer = null;
      }
    }

    // (Re)armed on every event and on stream open; fires only if 120s pass
    // with nothing in between.
    function armStallTimer() {
      clearStallTimer();
      stallTimer = setTimeout(() => {
        // Stalling means zero events have arrived yet, so state.jobId may
        // still be at its initial `null` (it's only ever set by an
        // update/error handler) — set it explicitly here too, the same way
        // onerror below does, or the stale-tag render guard would mask
        // `stalled` right along with everything else.
        setState((prev) => ({ ...prev, jobId, stalled: true }));
      }, STALL_TIMEOUT_MS);
    }

    armStallTimer();

    source.addEventListener("update", (event) => {
      try {
        const parsed = JSON.parse((event as MessageEvent<string>).data) as JobEvent;
        const done = TERMINAL_JOB_STATUSES.has(parsed.status);
        setState({ jobId, job: parsed, error: null, done, stalled: false });
        if (done) {
          clearStallTimer();
          source.close();
        } else {
          armStallTimer();
        }
      } catch {
        clearStallTimer();
        setState((prev) => ({
          jobId,
          job: prev.jobId === jobId ? prev.job : null,
          error: "Received a malformed update from the job stream.",
          done: false,
          stalled: false,
        }));
        source.close();
      }
    });

    source.onerror = () => {
      clearStallTimer();
      setState((prev) => ({
        jobId,
        job: prev.jobId === jobId ? prev.job : null,
        error: "Lost connection to the job stream.",
        done: false,
        stalled: false,
      }));
      source.close();
    };

    return () => {
      clearStallTimer();
      source.close();
    };
  }, [jobId]);

  if (state.jobId !== jobId) {
    return EMPTY_RESULT;
  }
  return { job: state.job, error: state.error, done: state.done, stalled: state.stalled };
}
