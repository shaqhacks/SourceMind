import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-foreground text-background hover:opacity-90",
  secondary: "border border-border hover:bg-muted-foreground/10",
  ghost: "hover:bg-muted-foreground/10",
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
      className={`rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...rest}
    />
  );
}
