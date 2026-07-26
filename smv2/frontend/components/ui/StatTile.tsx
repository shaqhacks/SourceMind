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
      <p className="font-heading text-3xl tracking-tight">{value}</p>
      <p className="mt-1 text-sm text-muted-foreground">{label}</p>
      {hint ? <div className="mt-2">{hint}</div> : null}
    </>
  );
  const frame = "block rounded-lg border border-divider bg-surface-raised p-4";
  return href ? (
    <Link href={href} className={`${frame} transition-[box-shadow,translate] hover:-translate-y-px hover:shadow-md`}>
      {body}
    </Link>
  ) : (
    <div className={frame}>{body}</div>
  );
}
