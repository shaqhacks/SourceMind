import Card from "@/components/ui/Card";
import type { TestSummaryOut } from "@/lib/api/client";

import { SOLID_THRESHOLD, toPercent } from "./testsFormat";

export interface ScoreHistoryCardProps {
  tests: TestSummaryOut[];
}

interface HistoryPoint {
  chapterLabel: string;
  score: number;
  createdAt: string;
}

/** Every graded attempt across every chapter/deck, oldest first — a plain
 * div bar chart (no chart library, per the brief) showing whether scores
 * are trending up. */
function historyPoints(tests: TestSummaryOut[]): HistoryPoint[] {
  return tests
    .flatMap((test) =>
      test.attempts
        .filter((attempt) => attempt.score !== null)
        .map((attempt) => ({
          chapterLabel: test.chapter_label ?? "Test",
          score: attempt.score as number,
          createdAt: attempt.created_at,
        })),
    )
    .sort((a, b) => Date.parse(a.createdAt) - Date.parse(b.createdAt));
}

export default function ScoreHistoryCard({ tests }: ScoreHistoryCardProps) {
  const points = historyPoints(tests);

  return (
    <Card className="flex flex-col gap-3 p-5">
      <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        Score history
      </span>
      {points.length === 0 ? (
        <p className="text-sm text-muted-foreground">No graded attempts yet.</p>
      ) : (
        <div
          role="img"
          aria-label={`Score history: ${points
            .map((p) => `${p.chapterLabel} ${toPercent(p.score)}%`)
            .join(", ")}`}
          className="flex h-[90px] items-end gap-2"
        >
          {points.map((point, index) => (
            <div
              key={index}
              aria-hidden="true"
              className="flex h-full flex-1 flex-col justify-end gap-1 text-center"
            >
              <div
                className={`rounded-t-lg rounded-b-sm ${
                  point.score >= SOLID_THRESHOLD ? "bg-sage-500" : "bg-accent-400"
                }`}
                style={{ height: `${Math.max(4, toPercent(point.score))}%` }}
              />
              <span className="text-[11px] text-muted-foreground">
                {point.chapterLabel} · {toPercent(point.score)}%
              </span>
            </div>
          ))}
        </div>
      )}
      <p className="text-[13px] text-muted-foreground">
        Missed questions are added to your flashcards automatically.
      </p>
    </Card>
  );
}
