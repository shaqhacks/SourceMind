import Link from "next/link";
import type { AnchorHTMLAttributes } from "react";

export type LinkButtonVariant = "primary" | "secondary";

// Mirrors Button.tsx's variant classes (that component only renders a
// <button>, not a navigable <a>) so these CTAs look identical while
// actually routing via next/link.
const VARIANTS: Record<LinkButtonVariant, string> = {
  primary: "bg-accent text-background hover:bg-accent-600 active:bg-accent-700",
  secondary:
    "border border-border bg-surface-raised hover:bg-foreground/[0.07] active:bg-foreground/[0.14]",
};

export interface LinkButtonProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  href: string;
  variant?: LinkButtonVariant;
}

export default function LinkButton({
  href,
  variant = "secondary",
  className = "",
  ...rest
}: LinkButtonProps) {
  return (
    <Link
      href={href}
      className={`inline-flex shrink-0 items-center justify-center rounded-md px-4 py-2 text-sm font-heading transition-colors ${VARIANTS[variant]} ${className}`}
      {...rest}
    />
  );
}
