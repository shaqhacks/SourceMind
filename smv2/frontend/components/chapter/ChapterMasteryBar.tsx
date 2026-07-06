import type { ChapterTestStats } from "@/lib/reader/types";

export interface ChapterMasteryBarProps {
  stats: ChapterTestStats | null;
}

function toPercent(score: number | null): number | null {
  return score === null ? null : Math.round(score * 100);
}

/**
 * "Chapter mastery: N%" — best_score as the headline number (what the
 * chapter test page's progress bar is meant to answer: "have I mastered
 * this yet"), latest_score as secondary context. A real width-based fill,
 * not a color-only indicator (WCAG 1.4.1) — same --accent used for the
 * global focus ring and other non-text UI, already verified 3:1+ against
 * the page background in both themes (see app/globals.css).
 */
export default function ChapterMasteryBar({ stats }: ChapterMasteryBarProps) {
  if (!stats || stats.attempts === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No attempts yet — take the chapter test below.
      </p>
    );
  }

  const bestPercent = toPercent(stats.best_score) ?? 0;
  const latestPercent = toPercent(stats.latest_score);

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="font-medium">Chapter mastery: {bestPercent}%</span>
        {latestPercent !== null && (
          <span className="text-muted-foreground">Latest: {latestPercent}%</span>
        )}
      </div>
      <div
        role="progressbar"
        aria-label="Chapter mastery"
        aria-valuenow={bestPercent}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-2 w-full overflow-hidden rounded-full bg-muted-foreground/20"
      >
        <div className="h-full rounded-full bg-accent" style={{ width: `${bestPercent}%` }} />
      </div>
    </div>
  );
}
