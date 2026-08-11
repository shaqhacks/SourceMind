"use client";

import { useMemo, useState } from "react";

import type { JobEvent } from "@/lib/hooks/useJobEvents";
import { formatElapsed, formatPhaseLabel, formatRecentActivity } from "@/lib/jobs/format";

export interface GenerationProgressProps {
  job: JobEvent | null;
  quiet: boolean;
  onCancel?: () => Promise<void>;
  onContinue?: () => void;
  compact?: boolean;
}

function currentElapsed(job: JobEvent | null): number {
  return Math.max(0, Math.floor(job?.progress?.elapsed_seconds ?? 0));
}

const NO_JOB_CANCEL_KEY = "__no-job__";

export default function GenerationProgress({
  job,
  quiet,
  onCancel,
  onContinue,
  compact = false,
}: GenerationProgressProps) {
  const [isCancelling, setIsCancelling] = useState(false);
  const [cancelRequestedFor, setCancelRequestedFor] = useState<string | null>(null);
  const [cancelError, setCancelError] = useState<string | null>(null);
  const phase = job?.progress?.stage ?? "preparing";
  const elapsed = currentElapsed(job);
  const phaseLabel = job && !job.progress ? "Queued" : formatPhaseLabel(phase);
  const isTerminal = job?.status === "cancelled" || job?.status === "succeeded" || job?.status === "failed";
  const cancelKey = job?.id ?? NO_JOB_CANCEL_KEY;
  const cancelRequested = cancelRequestedFor === cancelKey;

  const headline = useMemo(() => {
    if (job?.status === "cancelled") return "Cancelled";
    if (!job?.progress) return phaseLabel;
    return `${phaseLabel} · ${formatElapsed(elapsed)}`;
  }, [elapsed, job?.progress, job?.status, phaseLabel]);

  const recentActivity = formatRecentActivity(job?.progress?.last_activity_seconds);
  const showQuiet = quiet || elapsed >= 30;

  async function handleCancel() {
    if (!onCancel || isCancelling || (cancelRequested && !cancelError)) return;
    setIsCancelling(true);
    setCancelError(null);
    try {
      await onCancel();
      setCancelRequestedFor(cancelKey);
    } catch {
      setCancelRequestedFor(null);
      setCancelError("Could not cancel generation. Check your connection and try again.");
    } finally {
      setIsCancelling(false);
    }
  }

  return (
    <div
      className={[
        "rounded-lg border border-divider bg-surface-raised",
        compact ? "p-3 text-xs" : "p-4 text-sm",
      ].join(" ")}
    >
      <div role="status" aria-live="polite" aria-atomic="true" className="sr-only">
        {phaseLabel}
      </div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium text-foreground">{headline}</p>
          <p className="mt-1 text-muted-foreground">{recentActivity}</p>
          {showQuiet && job?.status !== "cancelled" && (
            <p className="mt-1 text-muted-foreground">
              This can take a little while. You can keep studying while generation continues.
            </p>
          )}
          {cancelError && !isTerminal && (
            <p role="alert" className="mt-2 text-status-serious">
              {cancelError}
            </p>
          )}
        </div>
        {(onCancel || onContinue) && !isTerminal && (
          <div className="flex shrink-0 flex-wrap gap-2">
            {onContinue && (
              <button
                type="button"
                onClick={onContinue}
                className="rounded-md border border-border bg-surface px-3 py-1.5 font-medium transition-colors hover:bg-foreground/[0.07] active:bg-foreground/[0.14]"
              >
                Continue in background
              </button>
            )}
            {onCancel && (
              <button
                type="button"
                onClick={() => void handleCancel()}
                disabled={isCancelling || (cancelRequested && !cancelError)}
                className="rounded-md border border-status-serious/40 bg-surface px-3 py-1.5 font-medium text-status-serious transition-colors hover:bg-status-serious-soft disabled:cursor-wait disabled:opacity-70"
              >
                {isCancelling
                  ? "Cancelling…"
                  : cancelError
                    ? "Retry cancel"
                    : cancelRequested
                      ? "Cancel requested"
                      : "Cancel generation"}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
