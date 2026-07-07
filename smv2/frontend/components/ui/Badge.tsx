import type { ReactNode } from "react";

export type BadgeTone = "good" | "warning" | "serious" | "neutral" | "accent";

const TONES: Record<BadgeTone, { classes: string; glyph: string }> = {
  good: { classes: "bg-status-good-soft text-status-good", glyph: "✓" },
  warning: { classes: "bg-status-warning-soft text-status-warning", glyph: "⚠" },
  serious: { classes: "bg-status-serious-soft text-status-serious", glyph: "✕" },
  neutral: { classes: "bg-muted-foreground/10 text-muted-foreground", glyph: "•" },
  accent: { classes: "bg-accent-soft text-accent", glyph: "●" },
};

export interface BadgeProps {
  tone: BadgeTone;
  children: ReactNode;
  /** Override the default glyph; pass a string/element, never null — a badge is never color-alone. */
  icon?: ReactNode;
}

export default function Badge({ tone, children, icon }: BadgeProps) {
  const { classes, glyph } = TONES[tone];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${classes}`}>
      <span aria-hidden="true">{icon ?? glyph}</span>
      {children}
    </span>
  );
}
