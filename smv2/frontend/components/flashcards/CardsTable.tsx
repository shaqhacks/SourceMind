import Badge from "@/components/ui/Badge";
import type { CardOut, ReviewQueueCardOut } from "@/lib/api/client";

export interface CardsTableProps {
  chapterTitle: string;
  cards: CardOut[];
  /** This course's due/new queue (getReviewQueue, capped at 200), keyed by
   * card id — the only source of a card's review state, since CardOut
   * itself carries none. A card absent here has a future due_at we have no
   * endpoint to read, so it renders as "Not due yet" rather than a guess. */
  dueCardsById: Map<string, ReviewQueueCardOut>;
}

/** Front_md is markdown; a table cell wants a plain, truncatable line, not
 * rendered HTML. Strips the common inline markers rather than parsing —
 * good enough for a preview string. */
function toPlainText(md: string): string {
  return md.replace(/[#*_`>~]/g, "").replace(/\s+/g, " ").trim();
}

export default function CardsTable({ chapterTitle, cards, dueCardsById }: CardsTableProps) {
  if (cards.length === 0) return null;

  return (
    <section className="flex flex-col gap-3" aria-labelledby="cards-table-heading">
      <h2 id="cards-table-heading" className="font-heading text-lg">
        All cards — {chapterTitle}
      </h2>
      <div className="overflow-x-auto rounded-lg border border-divider">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-divider text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
              <th className="px-4 py-2" style={{ width: "50%" }}>
                Front
              </th>
              <th className="px-4 py-2">Next review</th>
              <th className="px-4 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {cards.map((card) => {
              const queued = dueCardsById.get(card.id);
              return (
                <tr
                  key={card.id}
                  className="border-b border-divider last:border-b-0 hover:bg-foreground/[0.04]"
                >
                  <td className="max-w-md truncate px-4 py-2">{toPlainText(card.front_md)}</td>
                  <td className="px-4 py-2">
                    {queued && !queued.is_new ? (
                      <Badge tone="accent">Due now</Badge>
                    ) : queued && queued.is_new ? (
                      <Badge tone="neutral">New</Badge>
                    ) : (
                      <span className="text-xs text-muted-foreground">Not due yet</span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-xs text-muted-foreground">
                    {card.origin === "user" ? "User-added" : "Generated"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
