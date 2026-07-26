import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

// Organic system: primary = solid accent, text in ground color (the dark
// theme's ground is dark, matching theme.css's dark .btn-primary rule);
// secondary = surface fill + 24% ink border; ghost = accent text only.
const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-background hover:bg-accent-600 active:bg-accent-700",
  secondary:
    "border border-border bg-surface-raised hover:bg-foreground/[0.07] active:bg-foreground/[0.14]",
  ghost: "text-accent hover:bg-accent/10 active:bg-accent/[0.18]",
  danger: "border border-status-serious/40 text-status-serious hover:bg-status-serious-soft",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "px-2 py-1 text-xs",
  md: "px-4 py-2 text-sm",
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
      className={`rounded-md font-heading transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...rest}
    />
  );
}
