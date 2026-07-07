import Link from "next/link";

export interface ReviewCardProps {
  dueCount: number;
  href: string;
}

/**
 * Dashboard's second "jump back in" card, beside ContinueCard: one click
 * into a due-cards review session. Purely presentational — the caller
 * decides whether dueCount warrants showing it at all (>0) and what href
 * to send the click to (a specific course's due-now session when one can
 * be determined, the generic /review hub otherwise).
 */
export default function ReviewCard({ dueCount, href }: ReviewCardProps) {
  return (
    <Link
      href={href}
      className="block rounded-lg border border-border bg-accent/5 p-4 transition-colors hover:bg-accent/10"
    >
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Review</p>
      <h2 className="mt-1 text-lg font-semibold">
        {dueCount} card{dueCount === 1 ? "" : "s"} due — start your review
      </h2>
    </Link>
  );
}
