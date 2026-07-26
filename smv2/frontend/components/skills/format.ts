import type { BadgeTone } from "@/components/ui/Badge";
import type { ProgressBarTone } from "@/components/ui/ProgressBar";
import type { SkillStatus } from "@/lib/skills/placeholder";

export const STATUS_LABEL: Record<SkillStatus, string> = {
  solid: "Solid",
  growing: "Growing",
  struggling: "Struggling",
  locked: "Locked",
};

// Badge's "good" tone renders in the sage ramp and "accent" in the
// terracotta ramp (see Badge.tsx / globals.css --status-good), so this
// mapping already matches the design system's sage=met/solid,
// accent=weak/struggling semantics without inventing new tones.
export const STATUS_BADGE_TONE: Record<SkillStatus, BadgeTone> = {
  solid: "good",
  growing: "neutral",
  struggling: "accent",
  locked: "neutral",
};

export const STATUS_BAR_TONE: Record<SkillStatus, ProgressBarTone> = {
  solid: "sage",
  growing: "neutral",
  struggling: "accent",
  locked: "neutral",
};

/** "A" / "A and B" / "A, B, and C" */
export function joinNames(names: string[]): string {
  if (names.length === 0) return "";
  if (names.length === 1) return names[0];
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  return `${names.slice(0, -1).join(", ")}, and ${names[names.length - 1]}`;
}
