"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Markdown from "@/components/Markdown";
import RecoveryBanner from "@/components/RecoveryBanner";
import Button from "@/components/ui/Button";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  type ApiErrorDetail,
  findActiveLessonJob,
  generateLesson,
  getJob,
  getLessonEstimate,
  getSection,
  type LessonEstimateOut,
  type SectionDetailOut,
} from "@/lib/api/client";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { formatJobProgress } from "@/lib/jobs/format";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

export type LessonDisplayStatus = "none" | "queued" | "generating" | "ready" | "failed" | "stale";

export interface LessonPaneProps {
  sectionId: string;
  /** Bubbles the pane's current effective status up for the sidebar dot. */
  onStatusChange?: (status: LessonDisplayStatus) => void;
}

function formatEstimate(estimate: LessonEstimateOut): string {
  const seconds = Math.round(estimate.est_seconds);
  const cost =
    estimate.est_cost_usd === null ? null : `~$${estimate.est_cost_usd.toFixed(4)}`;
  const basis =
    estimate.based_on_calls > 0
      ? `based on ${estimate.based_on_calls} prior call${estimate.based_on_calls === 1 ? "" : "s"}`
      : "first generation — rough estimate";
  return cost ? `~${seconds}s · ${cost} · ${basis}` : `~${seconds}s · ${basis}`;
}

/** model/prompt-version are written together by generation.py; a legacy
 * or partial row with either missing degrades to the plain label. */
function formatGeneratedLabel(detail: SectionDetailOut): string {
  if (!detail.lesson_model || !detail.lesson_prompt_version) return "Generated";
  return `Generated · ${detail.lesson_model} · prompt ${detail.lesson_prompt_version}`;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "loaded"; detail: SectionDetailOut };

async function fetchDetail(sectionId: string): Promise<LoadState> {
  const { data, status } = await getSection(sectionId);
  if (!data) return { kind: "error", error: describeError(status, "Loading lesson") };
  return { kind: "loaded", detail: data };
}

/**
 * The reader's "s"-toggle lesson view. Owns its own get_section fetch
 * (independent of CourseReader's source-body cache — source text must
 * stay readable regardless of lesson state, so the two are deliberately
 * decoupled) plus the estimate, generation-job-watching, and
 * regenerate-confirmation logic.
 */
export default function LessonPane({ sectionId, onStatusChange }: LessonPaneProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [estimate, setEstimate] = useState<LessonEstimateOut | null>(null);
  const [localJobId, setLocalJobId] = useState<string | null>(null);
  const [discoveredJobId, setDiscoveredJobId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirmingRegenerate, setConfirmingRegenerate] = useState(false);
  // Tagged with the jobId it was fetched for (same idiom as useJobEvents'
  // own internal state) so staleness is a render-time comparison rather
  // than something an effect has to reset.
  const [failureInfo, setFailureInfo] = useState<{ jobId: string; message: string | null; detail: ApiErrorDetail | null } | null>(
    null,
  );

  const detail = state.kind === "loaded" ? state.detail : null;

  // A local job id (from a click we just made) always wins over the
  // rediscovered one for which job to watch. useJobEvents is keyed by
  // jobId — a stale (already-terminal) discoveredJobId left over from a
  // prior episode is harmless to keep passing it, it just stays `done`.
  const rawStatus = detail?.lesson_status ?? null;
  const watchedJobId = localJobId ?? discoveredJobId;
  const { job, done, stalled } = useJobEvents(watchedJobId);
  const failureMessage = failureInfo?.jobId === watchedJobId ? failureInfo.message : null;
  const failureDetail = failureInfo?.jobId === watchedJobId ? failureInfo.detail : null;

  // `!done` folds the watched job's own completion into this derivation —
  // once useJobEvents reports done, isInFlight drops on its own (no manual
  // reset needed), and a later regenerate click picks a new job id that
  // useJobEvents treats as fresh (it resets done per distinct jobId).
  const isInFlight =
    !done && (localJobId !== null || rawStatus === "queued" || rawStatus === "generating");

  const effectiveStatus: LessonDisplayStatus = isInFlight
    ? "generating"
    : rawStatus === "ready"
      ? detail?.lesson_stale
        ? "stale"
        : "ready"
      : rawStatus === "failed"
        ? "failed"
        : "none";

  // Mount / section-change fetch: both the section detail and the
  // generation estimate load as soon as the pane opens. No manual state
  // reset here for a `sectionId` change — the parent mounts this component
  // with `key={sectionId}`, so a section change is a fresh mount with
  // fresh initial state, not a footgun-prone synchronous reset-in-effect.
  useEffect(() => {
    let active = true;
    fetchDetail(sectionId).then((result) => {
      if (active) setState(result);
    });
    getLessonEstimate(sectionId).then(({ data }) => {
      if (active && data) setEstimate(data);
    });
    return () => {
      active = false;
    };
  }, [sectionId]);

  // Rediscover an in-flight job we didn't personally just start (e.g.
  // queued by generate_all_lessons, or from a prior session).
  useEffect(() => {
    if (!isInFlight || localJobId) return undefined;
    let active = true;
    findActiveLessonJob(sectionId).then((found) => {
      if (active) setDiscoveredJobId(found?.id ?? null);
    });
    return () => {
      active = false;
    };
  }, [isInFlight, localJobId, sectionId]);

  // Once the watched job settles, the cached detail is stale (status and,
  // if it succeeded, lesson_md/lesson_stale all changed server-side) —
  // refetch rather than guess the new values.
  useEffect(() => {
    if (!done) return;
    fetchDetail(sectionId).then(setState);
    notifyReviewSettled();
  }, [done, sectionId]);

  // JobEvent (the SSE snapshot) carries no error text — only {id, status,
  // progress} — so the actual failure message needs a follow-up plain REST
  // fetch. Only meaningful for a job watched this session (local or
  // rediscovered); a `lesson_status: "failed"` surviving from a much
  // earlier session with no job_id in memory falls back to the generic
  // message below instead.
  useEffect(() => {
    if (!done || job?.status !== "failed" || !watchedJobId) return;
    let active = true;
    getJob(watchedJobId).then(({ data }) => {
      if (active) {
        const detail = (data as { error_detail?: ApiErrorDetail | null } | undefined)?.error_detail ?? null;
        setFailureInfo({ jobId: watchedJobId, message: data?.error ?? null, detail });
      }
    });
    return () => {
      active = false;
    };
  }, [done, job?.status, watchedJobId]);

  const statusRef = useRef<LessonDisplayStatus | null>(null);
  useEffect(() => {
    if (statusRef.current === effectiveStatus) return;
    statusRef.current = effectiveStatus;
    onStatusChange?.(effectiveStatus);
  }, [effectiveStatus, onStatusChange]);

  const retryLoad = useCallback(() => {
    setState({ kind: "loading" });
    fetchDetail(sectionId).then(setState);
  }, [sectionId]);

  const handleGenerate = useCallback(
    async (force: boolean) => {
      setActionError(null);
      const { data, status } = await generateLesson(sectionId, force);
      if (data) {
        setLocalJobId(data.job_id);
        return;
      }
      if (status === 409) {
        // Someone/something else already has this in flight — resync
        // instead of surfacing an error for something that isn't one.
        retryLoad();
        return;
      }
      setActionError(describeError(status, "Starting lesson generation").message);
    },
    [sectionId, retryLoad],
  );

  if (state.kind === "loading") {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Loading lesson…
      </p>
    );
  }

  if (state.kind === "error") {
    return <ErrorBanner status={state.error.status} message={state.error.message} onRetry={retryLoad} />;
  }

  if (effectiveStatus === "generating") {
    return (
      <div role="status" className="text-sm text-muted-foreground">
        <p>{formatJobProgress(job, stalled)}</p>
      </div>
    );
  }

  if (effectiveStatus === "failed") {
    return (
      <div className="flex flex-col gap-2">
        <RecoveryBanner
          message={`Generation failed${failureMessage ? `: ${failureMessage}` : "."}`}
          onRetry={() => handleGenerate(true)}
          jobId={watchedJobId}
          errorDetail={failureDetail}
        />
        {actionError && <p className="text-xs text-status-serious">{actionError}</p>}
      </div>
    );
  }

  if (effectiveStatus === "ready" || effectiveStatus === "stale") {
    return (
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>{detail ? formatGeneratedLabel(detail) : "Generated"}</span>
            {effectiveStatus === "stale" && (
              <span className="rounded-[6px] bg-status-warning-soft px-2 py-0.5 font-medium text-status-warning">
                Prompt updated since generation
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={() => setConfirmingRegenerate(true)}
            className="text-xs font-medium text-accent"
          >
            Regenerate
          </button>
        </div>

        {confirmingRegenerate && (
          <div className="flex flex-col gap-2 rounded-lg border border-divider bg-surface-raised p-3 text-sm">
            <p>
              Regenerating replaces the current lesson
              {estimate ? ` (${formatEstimate(estimate)})` : ""}.
            </p>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => {
                  setConfirmingRegenerate(false);
                  void handleGenerate(true);
                }}
                className="font-medium text-accent"
              >
                Confirm
              </button>
              <button
                type="button"
                onClick={() => setConfirmingRegenerate(false)}
                className="text-muted-foreground"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {actionError && <p className="text-xs text-status-serious">{actionError}</p>}

        <Markdown>{detail?.lesson_md ?? ""}</Markdown>
      </div>
    );
  }

  // effectiveStatus === "none"
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        {estimate ? formatEstimate(estimate) : "Loading estimate…"}
      </p>
      <Button variant="primary" size="md" onClick={() => void handleGenerate(false)} className="self-start">
        Generate lesson
      </Button>
      {actionError && <p className="text-xs text-status-serious">{actionError}</p>}
    </div>
  );
}
