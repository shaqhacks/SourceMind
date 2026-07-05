"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import ErrorBanner from "@/components/ErrorBanner";
import { generateTest, listTests, type TestAttemptSummaryOut } from "@/lib/api/client";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

export interface QuizzesPanelProps {
  courseId: string;
}

interface FetchError {
  status?: number;
  message: string;
}

function describeError(status: number | undefined, action: string): FetchError {
  if (status === undefined) {
    return { message: `${action}: could not reach the API. Is the backend running?` };
  }
  return { status, message: `${action} failed (HTTP ${status}).` };
}

type ListState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "ready"; attempts: TestAttemptSummaryOut[] };

/**
 * TopBar-accessible popover: "Generate quiz" (job, like cards — no 409
 * dedup on the backend, so clicking twice just queues two jobs) + the
 * list of past attempts, each linking into the taking/review page.
 */
export default function QuizzesPanel({ courseId }: QuizzesPanelProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [listState, setListState] = useState<ListState>({ kind: "loading" });
  const [jobId, setJobId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  const { job, done, stalled } = useJobEvents(jobId);
  const isGenerating = jobId !== null && !done;

  // Deliberately doesn't reset to "loading" before refetching — the panel
  // just quietly replaces the list once the fresh fetch resolves, so
  // reopening shows the last-known list instead of flashing back to a
  // loading state (and keeps every setState here deferred inside a
  // .then(), which is what lets a plain function call from an effect
  // avoid the synchronous-setState-in-effect pitfall).
  const loadTests = useCallback(() => {
    listTests(courseId).then(({ data, status }) => {
      if (data) setListState({ kind: "ready", attempts: data });
      else setListState({ kind: "error", error: describeError(status, "Loading quizzes") });
    });
  }, [courseId]);

  useEffect(() => {
    if (open) loadTests();
  }, [open, loadTests]);

  useEffect(() => {
    if (!done) return;
    loadTests();
    notifyReviewSettled();
  }, [done, loadTests]);

  async function handleGenerate() {
    setStarting(true);
    setStartError(null);
    const { data, status } = await generateTest(courseId);
    setStarting(false);
    if (data) {
      setJobId(data.job_id);
      return;
    }
    setStartError(describeError(status, "Starting quiz generation").message);
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls="quizzes-panel"
        className="rounded-md border border-border px-2 py-1 text-sm"
      >
        Quizzes
      </button>
      {open && (
        <div
          id="quizzes-panel"
          role="dialog"
          aria-label="Quizzes"
          className="absolute right-0 z-10 mt-2 w-72 rounded-md border border-border bg-background p-4 text-sm shadow-lg"
        >
          <button
            type="button"
            onClick={() => void handleGenerate()}
            disabled={starting || isGenerating}
            className="mb-3 w-full rounded-md bg-black px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-black"
          >
            {isGenerating
              ? stalled
                ? "Still working — check back shortly."
                : job?.progress
                  ? `${job.progress.stage} — ${job.progress.pct}%`
                  : "Preparing…"
              : "Generate quiz"}
          </button>
          {startError && (
            <p className="mb-2 text-xs text-red-600 dark:text-red-400">{startError}</p>
          )}

          {listState.kind === "loading" && (
            <p role="status" className="text-xs text-muted-foreground">
              Loading…
            </p>
          )}
          {listState.kind === "error" && (
            <ErrorBanner
              status={listState.error.status}
              message={listState.error.message}
              onRetry={loadTests}
            />
          )}
          {listState.kind === "ready" && (
            <ul className="flex flex-col gap-1">
              {listState.attempts.length === 0 ? (
                <li className="text-xs text-muted-foreground">No quizzes yet.</li>
              ) : (
                listState.attempts.map((attempt) => (
                  <li key={attempt.id}>
                    <button
                      type="button"
                      onClick={() => {
                        setOpen(false);
                        router.push(`/course/${courseId}/test/${attempt.id}`);
                      }}
                      className="flex w-full items-center justify-between rounded px-2 py-1 text-left text-xs hover:bg-muted-foreground/10"
                    >
                      <span>{attempt.question_count} questions</span>
                      <span className="text-muted-foreground">
                        {attempt.score !== null
                          ? `${Math.round(attempt.score * 100)}%`
                          : "In progress"}
                      </span>
                    </button>
                  </li>
                ))
              )}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
