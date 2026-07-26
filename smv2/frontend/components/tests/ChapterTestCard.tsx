"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";

import Button from "@/components/ui/Button";
import { describeError } from "@/lib/api/errors";
import { getTest, retakeTest, type TestAttemptSummaryOut, type TestSummaryOut } from "@/lib/api/client";

import ScoreRing from "./ScoreRing";
import { attemptsForChapter, formatRelativeDate, SOLID_THRESHOLD, toPercent } from "./testsFormat";

export interface ChapterTestCardProps {
  courseId: string;
  chapterLabel: string;
  tests: TestSummaryOut[];
  attempts: number;
  bestScore: number;
}

interface MissedQuestion {
  question: string;
  yourAnswer: string;
}

type MissedState =
  | { kind: "collapsed" }
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; items: MissedQuestion[] };

/** The chapter's own most recent scored attempt, across every deck
 * generated for it — used both for "last taken" and the "Missed last
 * time" lazy fetch, since attempts (unlike best_score) aren't aggregated
 * server-side. */
function latestScoredAttempt(
  tests: TestSummaryOut[],
  chapterLabel: string,
): { test: TestSummaryOut; attempt: TestAttemptSummaryOut } | null {
  const scored = attemptsForChapter(tests, chapterLabel).filter(({ attempt }) => attempt.score !== null);
  return scored[0] ?? null;
}

export default function ChapterTestCard({
  courseId,
  chapterLabel,
  tests,
  attempts,
  bestScore,
}: ChapterTestCardProps) {
  const router = useRouter();
  const [retaking, setRetaking] = useState(false);
  const [retakeError, setRetakeError] = useState<string | null>(null);
  const [missed, setMissed] = useState<MissedState>({ kind: "collapsed" });

  const chapterTests = attemptsForChapter(tests, chapterLabel);
  const latestAttemptEntry = chapterTests[0] ?? null;
  const latestScored = latestScoredAttempt(tests, chapterLabel);
  // Retake targets the most recently generated deck for this chapter —
  // the one a user browsing this card actually means by "retake".
  const retakeTarget = [...tests]
    .filter((test) => test.chapter_label === chapterLabel)
    .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
  const isWeak = bestScore < SOLID_THRESHOLD;
  const percent = toPercent(bestScore);
  const questionCount = retakeTarget?.question_count ?? null;

  const handleRetake = useCallback(async () => {
    if (!retakeTarget) return;
    setRetaking(true);
    setRetakeError(null);
    const { data, status } = await retakeTest(retakeTarget.id);
    setRetaking(false);
    if (data) {
      router.push(`/course/${courseId}/test/${data.attempt_id}`);
      return;
    }
    setRetakeError(describeError(status, "Starting a retake").message);
  }, [retakeTarget, courseId, router]);

  const toggleMissed = useCallback(() => {
    if (missed.kind !== "collapsed") {
      setMissed({ kind: "collapsed" });
      return;
    }
    if (!latestScored) return;
    setMissed({ kind: "loading" });
    getTest(latestScored.attempt.id).then(({ data, status }) => {
      if (!data || !data.results) {
        setMissed({
          kind: "error",
          message: describeError(status, "Loading missed questions").message,
        });
        return;
      }
      const items = data.results
        .map((r, index) => ({
          question: data.questions[index]?.question ?? "",
          yourAnswer:
            r.your_answer !== null ? data.questions[index]?.choices[r.your_answer] ?? "" : "(none)",
          correct: r.correct,
        }))
        .filter((item) => !item.correct)
        .map(({ question, yourAnswer }) => ({ question, yourAnswer }));
      setMissed({ kind: "loaded", items });
    });
  }, [missed.kind, latestScored]);

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-divider bg-surface-raised p-5 shadow-sm">
      <div className="flex items-center gap-4">
        <div className="min-w-0 flex-1">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {chapterLabel}
          </span>
          <p className="mt-1 text-base font-semibold">
            {isWeak
              ? `Best score ${percent}% — below your 80% target`
              : `Best score ${percent}% — solid`}
          </p>
          <p className="mt-0.5 text-[13px] text-muted-foreground">
            {attempts} attempt{attempts === 1 ? "" : "s"}
            {questionCount !== null ? ` · ${questionCount} questions` : ""}
            {latestAttemptEntry
              ? ` · last taken ${formatRelativeDate(latestAttemptEntry.attempt.created_at)}`
              : ""}
          </p>
        </div>
        <ScoreRing score={bestScore} />
        <Button
          variant={isWeak ? "primary" : "secondary"}
          onClick={() => void handleRetake()}
          disabled={retaking || !retakeTarget}
          title="Same questions, no generation cost"
        >
          Retake
        </Button>
      </div>
      {retakeError && <p className="text-xs text-red-600 dark:text-red-400">{retakeError}</p>}

      {isWeak && latestScored && (
        <div className="flex flex-col gap-2 border-t border-divider pt-3">
          <button
            type="button"
            onClick={toggleMissed}
            aria-expanded={missed.kind !== "collapsed"}
            className="self-start text-xs font-bold uppercase tracking-wide text-muted-foreground hover:text-foreground"
          >
            Missed last time
          </button>
          {missed.kind === "loading" && (
            <p role="status" className="text-xs text-muted-foreground">
              Loading…
            </p>
          )}
          {missed.kind === "error" && (
            <p className="text-xs text-red-600 dark:text-red-400">{missed.message}</p>
          )}
          {missed.kind === "loaded" && missed.items.length === 0 && (
            <p className="text-xs text-muted-foreground">No misses on the latest attempt.</p>
          )}
          {missed.kind === "loaded" && missed.items.length > 0 && (
            <ul className="flex flex-col gap-2">
              {missed.items.map((item, index) => (
                <li key={index} className="flex items-center justify-between gap-3 text-sm">
                  <span className="min-w-0 truncate">{item.question}</span>
                  <button
                    type="button"
                    onClick={() => router.push(`/course/${courseId}/test/${latestScored.attempt.id}`)}
                    className="shrink-0 text-[13px] font-medium text-accent hover:underline"
                  >
                    Review answer
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
