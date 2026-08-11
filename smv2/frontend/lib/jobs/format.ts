import type { JobEvent } from "@/lib/hooks/useJobEvents";

export interface FormatJobProgressOptions {
  /** Set false to omit the trailing " — {message}" segment — QuizzesPanel's
   * button is width-constrained and deliberately shows only stage/pct.
   * Default true. */
  includeMessage?: boolean;
}

/** The three-state in-flight job status line: stalled, has progress, or
 * still preparing (job accepted but no SSE update yet). */
export function formatJobProgress(
  job: JobEvent | null,
  stalled: boolean,
  options: FormatJobProgressOptions = {},
): string {
  if (stalled) return "Still working — check back shortly.";
  if (!job?.progress) return "Preparing…";
  const { stage, pct, message } = job.progress;
  const includeMessage = options.includeMessage ?? true;
  const pctText = typeof pct === "number" ? `${pct}%` : "working";
  const base = `${stage} — ${pctText}`;
  return includeMessage ? `${base} — ${message}` : base;
}

export function formatPhaseLabel(phase: string): string {
  return phase
    .split(/[_-]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ") || "Preparing";
}

export function formatElapsed(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds.toString().padStart(2, "0")}s`;
}

export function formatRecentActivity(secondsSinceActivity: number | undefined): string {
  if (secondsSinceActivity === undefined || secondsSinceActivity <= 10) {
    return "Model active recently.";
  }
  return `Model active ${formatElapsed(secondsSinceActivity)} ago.`;
}
