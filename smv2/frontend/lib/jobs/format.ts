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
  return includeMessage ? `${stage} — ${pct}% — ${message}` : `${stage} — ${pct}%`;
}
