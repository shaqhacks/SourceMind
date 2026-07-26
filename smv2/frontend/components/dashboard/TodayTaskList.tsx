"use client";

import { useRouter } from "next/navigation";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import ProgressBar from "@/components/ui/ProgressBar";
import type { TaskCard } from "@/lib/dashboard/taskCards";

export interface TodayTaskListProps {
  items: TaskCard[];
}

// Position, not card type, drives the numbered circle's color (mock: card 1
// accent, card 2 sage, card 3 neutral) — whichever signals happen to apply
// still read as a simple ordered list.
const CIRCLE_TONES = [
  "bg-accent-200 text-accent-700",
  "bg-sage-200 text-sage-700",
  "bg-neutral-200 text-neutral-700",
];

/**
 * "Today's study plan" — the redesigned Home's left column. Purely
 * presentational (see lib/dashboard/taskCards.ts for the derivation);
 * navigates via router.push so the action is a real <button> rather than a
 * <button> nested inside a <Link> (invalid — <a> may not contain
 * interactive content).
 */
export default function TodayTaskList({ items }: TodayTaskListProps) {
  const router = useRouter();

  if (items.length === 0) {
    return (
      <Card className="items-center justify-center gap-1 py-10 text-center">
        <p className="font-medium">Nothing on today&apos;s plan</p>
        <p className="text-sm text-muted-foreground">
          Open a course or upload a PDF to get started.
        </p>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-3.5">
      {items.map((item, index) => (
        <Card key={item.id} className="flex flex-row items-center gap-4 py-5">
          <span
            aria-hidden="true"
            className={`flex h-11 w-11 flex-none items-center justify-center rounded-full font-heading text-base ${CIRCLE_TONES[index] ?? CIRCLE_TONES[2]}`}
          >
            {index + 1}
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-base font-bold">{item.title}</p>
            <p className="mt-0.5 text-[13px] text-muted-foreground">{item.meta}</p>
            {item.progressPercent != null && (
              <div className="mt-2">
                <ProgressBar percent={item.progressPercent} label={item.title} />
              </div>
            )}
          </div>
          <Button variant={item.actionVariant} onClick={() => router.push(item.actionHref)}>
            {item.actionLabel}
          </Button>
        </Card>
      ))}
    </div>
  );
}
