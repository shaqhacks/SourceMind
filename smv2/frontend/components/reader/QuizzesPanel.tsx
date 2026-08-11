"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import ErrorBanner from "@/components/ErrorBanner";
import GenerationProgress from "@/components/jobs/GenerationProgress";
import RecoveryBanner from "@/components/RecoveryBanner";
import Button from "@/components/ui/Button";
import { describeError, type FetchError } from "@/lib/api/errors";
import { generateTest, listTests, type TestSummaryOut } from "@/lib/api/client";
import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import { useDismissOnOutsideOrEscape } from "@/lib/hooks/useDismissOnOutsideOrEscape";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { useJobFailure } from "@/lib/hooks/useJobFailureMessage";
import { cancelGenerationJob } from "@/lib/jobs/cancel";
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
  const [startError, setStartError] = useState<FetchError | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const panelRef = useDialogFocus<HTMLDivElement>(open, { trap: false });
  const close = useCallback(() => setOpen(false), []);
  useDismissOnOutsideOrEscape(open, close, containerRef);

  const { job, done, stalled } = useJobEvents(jobId);
  const isGenerating = jobId !== null && !done;
  const jobFailed = done && job?.status === "failed";
  const failureInfo = useJobFailure(jobFailed, jobId);

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

  async function handleGenerate() {
    setStarting(true);
    setStartError(null);
    const { data, status, error } = await generateTest(courseId);
    setStarting(false);
    if (data) {
      setJobId(data.job_id);
      return;
    }
    setStartError(describeError(status, "Starting quiz generation", error));
  }

  return (
    <div ref={containerRef} className="relative">
      <Button
        variant="toolbar"
        size="toolbar"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls="quizzes-panel"
        className="font-medium"
      >
        Quizzes
      </Button>
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
            {isGenerating ? "Generating quiz" : "Generate quiz"}
          </Button>
          {isGenerating && (
            <div className="mb-3">
              <GenerationProgress
                job={stalled ? null : job}
                quiet={stalled}
                compact
                onCancel={jobId ? () => cancelGenerationJob(jobId) : undefined}
                onContinue={() => {
                  setOpen(false);
                  router.push(`/course/${courseId}`);
                }}
              />
            </div>
          )}
          {jobFailed && (
            <div className="mb-3">
              <RecoveryBanner
                message={`Generation failed${failureInfo.message ? `: ${failureInfo.message}` : "."}`}
                onRetry={() => void handleGenerate()}
                jobId={jobId}
                errorDetail={failureInfo.detail}
              />
            </div>
          )}
          {startError && (
            <div className="mb-2">
              <RecoveryBanner
                message={startError.message}
                errorDetail={startError.detail}
                onRetry={() => void handleGenerate()}
              />
            </div>
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
