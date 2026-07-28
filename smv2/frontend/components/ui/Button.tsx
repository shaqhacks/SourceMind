import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "toolbar";
export type ButtonSize = "sm" | "md" | "toolbar";

// Organic system: primary = solid accent, text in ground color (the dark
// theme's ground is dark, matching theme.css's dark .btn-primary rule);
// secondary = surface fill + 24% ink border; ghost = accent text only.
// Primary's fill is accent-700, not the base --accent: at --accent's own
// value (#c67139 light / already-fine in dark), the light-theme pairing
// against the light `text-background` only reaches ~3.45:1, under WCAG
// AA's 4.5:1 for text. accent-700 is the lightest rung on the ramp that
// clears 4.5:1 (light: ~6.5:1; dark's accent-700 is ~10.6:1, still well
// clear). hover/active step one/two further rungs out (accent-800/900) to
// keep the existing darken-on-interaction direction relative to the new
// resting shade. --accent itself is untouched — it's still used for focus
// rings and non-text fills (e.g. selection swatches) where this contrast
// rule doesn't apply.
const VARIANTS: Record<ButtonVariant, string> = {
  primary: "font-heading bg-accent-700 text-background hover:bg-accent-800 active:bg-accent-900",
  secondary:
    "font-heading border border-border bg-surface-raised hover:bg-foreground/[0.07] active:bg-foreground/[0.14]",
  ghost: "font-heading text-accent hover:bg-accent/10 active:bg-accent/[0.18]",
  danger:
    "font-heading border border-status-serious/40 text-status-serious hover:bg-status-serious-soft",
  // Small reader/settings toolbar chrome (GenerateAllLessons, QuizzesPanel's
  // toggle, TypographyControls' "Aa") — the same border/surface/hover/active
  // chrome as `secondary`, but WITHOUT font-heading: these are plain-text
  // toolbar buttons, not font-heading display CTAs.
  toolbar: "border border-border bg-surface-raised hover:bg-foreground/[0.07] active:bg-foreground/[0.14]",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "px-2 py-1 text-xs",
  md: "px-4 py-2 text-sm",
  toolbar: "px-3 py-1.5 text-[13px]",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

export default function Button({
  variant = "secondary",
  size = "md",
  className = "",
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={`rounded-md transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...rest}
    />
  );
}
