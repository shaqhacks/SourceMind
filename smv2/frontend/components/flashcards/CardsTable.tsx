"use client";

import { useState } from "react";

import ReviewGradeControls from "@/components/review/ReviewGradeControls";
import Badge from "@/components/ui/Badge";
import type { CardOut, ReviewQueueCardOut } from "@/lib/api/client";

export interface CardsTableProps {
  chapterTitle: string;
  cards: CardOut[];
  /** Exact review-selection metadata for the loaded cards, keyed by card id
   * — the only source of scheduler state, since CardOut itself carries none. */
  dueCardsById: Map<string, ReviewQueueCardOut>;
}

/** Front_md is markdown; a table cell wants a plain, truncatable line, not
 * rendered HTML. Strips the common inline markers rather than parsing —
 * good enough for a preview string. */
function toPlainText(md: string): string {
  return md.replace(/[#*_`>~]/g, "").replace(/\s+/g, " ").trim();
}

export default function CardsTable({ chapterTitle, cards, dueCardsById }: CardsTableProps) {
  const [revealedById, setRevealedById] = useState<Record<string, boolean>>({});

  if (cards.length === 0) return null;

  return (
    <section className="flex flex-col gap-3" aria-labelledby="cards-table-heading">
      <h2 id="cards-table-heading" className="font-heading text-lg">
        All cards — {chapterTitle}
      </h2>
      <ul
        aria-labelledby="cards-table-heading"
        className="divide-y divide-divider rounded-lg border border-divider"
      >
        {cards.map((card) => {
          const queued = dueCardsById.get(card.id);
          const revealed = revealedById[card.id] === true;
          return (
            <li key={card.id} className="flex flex-col gap-3 p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{toPlainText(card.front_md)}</p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {queued?.is_due ? (
                      <Badge tone="accent">Due now</Badge>
                    ) : queued?.is_new ? (
                      <Badge tone="neutral">New</Badge>
                    ) : (
                      <span className="text-xs text-muted-foreground">Not due yet</span>
                    )}
                    {queued?.last_grade === 1 && <Badge tone="accent">Needs attention</Badge>}
                    <span className="text-xs text-muted-foreground">
                      {card.origin === "user" ? "User-added" : "Generated"}
                    </span>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() =>
                    setRevealedById((current) => ({ ...current, [card.id]: !revealed }))
                  }
                  aria-expanded={revealed}
                  className="self-start rounded-md border border-border bg-surface-raised px-3 py-1.5 font-heading text-xs transition-colors hover:bg-foreground/[0.07] active:bg-foreground/[0.14]"
                >
                  {revealed ? "Hide answer" : "Show answer"}
                </button>
              </div>
              {revealed && (
                <div className="rounded-md bg-foreground/[0.035] p-3">
                  <p className="text-sm">{toPlainText(card.back_md)}</p>
                  {queued && <ReviewGradeControls card={queued} className="mt-3" />}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
