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
  const bg = variant === "tinted" ? "bg-accent-soft/60" : "bg-surface-raised";
  const hover = interactive ? "transition-colors hover:border-muted-foreground" : "";
  return (
    <div
      className={`rounded-lg border border-border p-4 ${bg} ${hover} ${className}`}
      {...rest}
    />
  );
}
