import { SOLID_THRESHOLD, toPercent } from "./testsFormat";

export interface ScoreRingProps {
  /** 0-1 fraction, same convention as best_score/latest_score elsewhere. */
  score: number;
}

/** 54px conic-gradient ring: accent below the 80% solid threshold, sage at
 * or above it. role="img" + a text alternative — the fill is decorative,
 * the centered percent label carries the actual information. */
export default function ScoreRing({ score }: ScoreRingProps) {
  const percent = toPercent(score);
  const color = score >= SOLID_THRESHOLD ? "var(--sage-500)" : "var(--accent)";
  return (
    <span
      role="img"
      aria-label={`Score ${percent}%`}
      className="inline-flex h-[54px] w-[54px] shrink-0 items-center justify-center rounded-full"
      style={{ background: `conic-gradient(${color} 0 ${percent}%, var(--neutral-200) ${percent}% 100%)` }}
    >
      <span className="flex h-[42px] w-[42px] items-center justify-center rounded-full bg-surface-raised font-heading text-sm">
        {percent}%
      </span>
    </span>
  );
}
