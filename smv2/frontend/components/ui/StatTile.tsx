import Link from "next/link";
import type { ReactNode } from "react";

export interface StatTileProps {
  value: string | number;
  label: string;
  href?: string;
  hint?: ReactNode;
}

/** Hero-number tile (dataviz spec): the number wears text tokens, never a series color. */
export default function StatTile({ value, label, hint, href }: StatTileProps) {
  const body = (
    <>
      <p className="text-3xl font-semibold tracking-tight">{value}</p>
      <p className="mt-1 text-sm text-muted-foreground">{label}</p>
      {hint ? <div className="mt-2">{hint}</div> : null}
    </>
  );
  const frame = "block rounded-lg border border-border bg-surface-raised p-4";
  return href ? (
    <Link href={href} className={`${frame} transition-colors hover:border-muted-foreground`}>
      {body}
    </Link>
  ) : (
    <div className={frame}>{body}</div>
  );
}
