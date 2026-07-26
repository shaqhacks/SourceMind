export type ProgressBarTone = "accent" | "sage" | "neutral";

export interface ProgressBarProps {
  percent: number;
  label: string;
  /** Organic semantics: sage = solid/met, accent = attention, neutral = inactive. */
  tone?: ProgressBarTone;
}

const FILLS: Record<ProgressBarTone, string> = {
  accent: "bg-accent",
  sage: "bg-sage-500",
  neutral: "bg-neutral-400",
};

export default function ProgressBar({ percent, label, tone = "accent" }: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, Math.round(percent)));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={clamped}
      className="h-1.5 w-full overflow-hidden rounded-full bg-neutral-200"
    >
      <div
        className={`h-full rounded-full ${FILLS[tone]}`}
        style={{ width: `${clamped}%` }}
      />
    </div>
  );
}
