"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import ErrorBanner from "@/components/ErrorBanner";
import Button from "@/components/ui/Button";
import { describeError, type FetchError } from "@/lib/api/errors";
import { generateTest, getJob, listTests, type TestSummaryOut } from "@/lib/api/client";
import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import { useDismissOnOutsideOrEscape } from "@/lib/hooks/useDismissOnOutsideOrEscape";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { formatJobProgress } from "@/lib/jobs/format";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

export interface QuizzesPanelProps {
  courseId: string;
}

type ListState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "ready"; tests: TestSummaryOut[] };

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
  // Tagged with the jobId it was fetched for (same idiom as useJobEvents'
  // own internal state) so staleness is a render-time comparison rather
  // than something an effect has to reset.
  const [failureInfo, setFailureInfo] = useState<{ jobId: string; message: string | null } | null>(
    null,
  );
  const containerRef = useRef<HTMLDivElement>(null);
  const panelRef = useDialogFocus<HTMLDivElement>(open, { trap: false });
  const close = useCallback(() => setOpen(false), []);
  useDismissOnOutsideOrEscape(open, close, containerRef);

  const { job, done, stalled } = useJobEvents(jobId);
  const isGenerating = jobId !== null && !done;
  const jobFailed = done && job?.status === "failed";
  const failureMessage = failureInfo?.jobId === jobId ? failureInfo.message : null;

  // Deliberately doesn't reset to "loading" before refetching — the panel
  // just quietly replaces the list once the fresh fetch resolves, so
  // reopening shows the last-known list instead of flashing back to a
  // loading state (and keeps every setState here deferred inside a
  // .then(), which is what lets a plain function call from an effect
  // avoid the synchronous-setState-in-effect pitfall).
  const loadTests = useCallback(() => {
    listTests(courseId).then(({ data, status }) => {
      if (data) setListState({ kind: "ready", tests: data });
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

  // JobEvent (the SSE snapshot) carries no error text — only {id, status,
  // progress} — so surfacing the actual failure message needs a follow-up
  // plain REST fetch.
  useEffect(() => {
    if (!jobFailed || !jobId) return;
    let active = true;
    getJob(jobId).then(({ data }) => {
      if (active) setFailureInfo({ jobId, message: data?.error ?? null });
    });
    return () => {
      active = false;
    };
  }, [jobFailed, jobId]);

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
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls="quizzes-panel"
        className="rounded-md border border-border bg-surface-raised px-3 py-1.5 text-[13px] font-medium transition-colors hover:bg-foreground/[0.07] active:bg-foreground/[0.14]"
      >
        Quizzes
      </button>
      {open && (
        <div
          ref={panelRef}
          id="quizzes-panel"
          role="dialog"
          aria-label="Quizzes"
          tabIndex={-1}
          className="absolute right-0 z-10 mt-2 w-72 rounded-lg border border-divider bg-surface-raised p-4 text-sm shadow-md"
        >
          <Button
            variant="primary"
            size="md"
            onClick={() => void handleGenerate()}
            disabled={starting || isGenerating}
            aria-live="polite"
            className="mb-3 w-full"
          >
            {isGenerating ? formatJobProgress(job, stalled, { includeMessage: false }) : "Generate quiz"}
          </Button>
          {jobFailed && (
            <div className="mb-3">
              <ErrorBanner
                message={`Generation failed${failureMessage ? `: ${failureMessage}` : "."}`}
                onRetry={() => void handleGenerate()}
              />
            </div>
          )}
          {startError && (
            <p className="mb-2 text-xs text-status-serious">{startError}</p>
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
              {listState.tests.length === 0 ? (
                <li className="text-xs text-muted-foreground">
                  No quizzes yet — generate one above.
                </li>
              ) : (
                // Each row is a test/deck; clicking jumps into its most
                // recent attempt (TestSummaryOut's own attempts are
                // newest-first) — retaking a specific test lives on the
                // chapter test page's fuller history, not this popover.
                listState.tests.map((test) => {
                  const latest = test.attempts[0];
                  return (
                    <li key={test.id}>
                      <button
                        type="button"
                        disabled={!latest}
                        onClick={() => {
                          if (!latest) return;
                          setOpen(false);
                          router.push(`/course/${courseId}/test/${latest.id}`);
                        }}
                        className="flex w-full items-center justify-between rounded px-2 py-1 text-left text-xs hover:bg-muted-foreground/10 disabled:opacity-50"
                      >
                        <span>{test.question_count} questions</span>
                        <span className="text-muted-foreground">
                          {latest?.score != null ? `${Math.round(latest.score * 100)}%` : "In progress"}
                        </span>
                      </button>
                    </li>
                  );
                })
              )}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
