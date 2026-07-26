import type { HTMLAttributes } from "react";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: "plain" | "tinted";
  /** Adds hover affordance when the card wraps/sits under a link. */
  interactive?: boolean;
}

export default function Card({
  variant = "plain",
  interactive = false,
  className = "",
  ...rest
}: CardProps) {
  const bg = variant === "tinted" ? "bg-accent-soft" : "bg-surface-raised";
  const hover = interactive
    ? "transition-[box-shadow,translate] hover:-translate-y-px hover:shadow-md"
    : "";
  return (
    <div
      className={`rounded-lg border border-divider p-4 ${bg} ${hover} ${className}`}
      {...rest}
    />
  );
}
