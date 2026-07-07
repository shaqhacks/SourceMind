"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import ErrorBanner from "@/components/ErrorBanner";
import Button from "@/components/ui/Button";
import { describeError } from "@/lib/api/errors";
import { createCourse, getJob, startIngest, uploadAsset } from "@/lib/api/client";
import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";
import { formatJobProgress } from "@/lib/jobs/format";
import { defaultTitleFromFilename } from "@/lib/upload/filename";

export interface UploadFlowProps {
  files: File[];
  onClose: () => void;
}

interface UploadItem {
  file: File;
  status: "pending" | "success" | "error";
  error?: string;
}

type Step =
  | { kind: "title"; title: string }
  | { kind: "creating" }
  | { kind: "uploading"; courseId: string; items: UploadItem[] }
  | { kind: "starting-ingest"; courseId: string; items: UploadItem[] }
  | { kind: "ingesting"; courseId: string; jobId: string; items: UploadItem[] }
  | { kind: "ingest-failed"; courseId: string; items: UploadItem[]; message: string }
  | { kind: "fatal"; message: string };

const STEPS = ["Name", "Upload", "Ingest"] as const;

/**
 * Maps the state machine above onto the 3-step "Name -> Upload -> Ingest"
 * indicator. "creating" folds into Upload (course creation is an invisible
 * prerequisite, not a step a user perceives); "starting-ingest" folds into
 * Ingest (it's that phase's own kickoff); "fatal" (course creation itself
 * failed) stays at Name since the flow never actually left it.
 */
function currentStepFor(step: Step): 0 | 1 | 2 {
  switch (step.kind) {
    case "title":
    case "fatal":
      return 0;
    case "creating":
    case "uploading":
      return 1;
    case "starting-ingest":
    case "ingesting":
    case "ingest-failed":
      return 2;
  }
}

/**
 * Modal walking a freshly-selected/dropped batch of PDFs through: create
 * course -> upload each file (independently — one failure doesn't stop the
 * rest) -> start_ingest -> live SSE progress -> straight into the reader.
 * The detected outline is no longer confirmed here (owner decision): outline
 * editing lives in the reader itself (TopBar "Edit outline" / "o"), reusing
 * the same OutlineConfirmation editing UI against the live course instead of
 * gating first sight of the reader behind it.
 */
export default function UploadFlow({ files, onClose }: UploadFlowProps) {
  const router = useRouter();
  const [step, setStep] = useState<Step>({
    kind: "title",
    title: defaultTitleFromFilename(files[0]?.name ?? ""),
  });
  // This modal is mounted/unmounted by the parent (no internal open/close
  // toggle), so "open" is just "true" for its whole lifetime — the hook's
  // close-focus-restore fires naturally on unmount.
  const dialogRef = useDialogFocus<HTMLDivElement>(true);
  useKeyboardShortcuts({ escape: onClose });

  const activeJobId = step.kind === "ingesting" ? step.jobId : null;
  const { job, error: sseError, done, stalled } = useJobEvents(activeJobId);

  const runUploadsAndIngest = useCallback(
    async (courseId: string) => {
      const initialItems: UploadItem[] = files.map((file) => ({ file, status: "pending" }));
      setStep({ kind: "uploading", courseId, items: initialItems });

      const settled = await Promise.all(
        files.map(async (file, index) => {
          const { data, status } = await uploadAsset(courseId, file);
          const result: UploadItem = data
            ? { file, status: "success" }
            : { file, status: "error", error: describeError(status, "Upload").message };
          setStep((prev) =>
            prev.kind === "uploading"
              ? { ...prev, items: prev.items.map((item, i) => (i === index ? result : item)) }
              : prev,
          );
          return result;
        }),
      );

      setStep({ kind: "starting-ingest", courseId, items: settled });

      const { data: ingestData, status: ingestStatus } = await startIngest(courseId);
      if (!ingestData) {
        setStep({
          kind: "ingest-failed",
          courseId,
          items: settled,
          message: describeError(ingestStatus, "Starting ingest").message,
        });
        return;
      }

      setStep({ kind: "ingesting", courseId, jobId: ingestData.job_id, items: settled });
    },
    [files],
  );

  const handleCreateCourse = useCallback(async () => {
    if (step.kind !== "title") return;
    const title = step.title.trim() || "Untitled course";
    setStep({ kind: "creating" });

    const { data, status } = await createCourse({ title });
    if (!data) {
      setStep({ kind: "fatal", message: describeError(status, "Creating the course").message });
      return;
    }

    await runUploadsAndIngest(data.id);
  }, [step, runUploadsAndIngest]);

  const retryIngest = useCallback(() => {
    if (step.kind !== "ingest-failed") return;
    void runUploadsAndIngest(step.courseId);
  }, [step, runUploadsAndIngest]);

  // Ingest job succeeded: go straight into the reader. Outline editing is
  // no longer a gate here — see this component's own doc comment.
  useEffect(() => {
    if (!done || !job || job.status !== "succeeded" || step.kind !== "ingesting") return;
    router.push(`/course/${step.courseId}`);
  }, [done, job, step, router]);

  // Ingest job reported failure (distinct from a dropped SSE connection).
  // The SSE snapshot is just {id, status, progress} — no error text — so
  // the actual message needs a follow-up plain REST fetch.
  useEffect(() => {
    if (!done || !job || job.status !== "failed" || step.kind !== "ingesting") return;
    const courseId = step.courseId;
    const items = step.items;
    let active = true;
    getJob(job.id).then(({ data }) => {
      if (!active) return;
      setStep({ kind: "ingest-failed", courseId, items, message: data?.error ?? "Ingest failed." });
    });
    return () => {
      active = false;
    };
  }, [done, job, step]);

  function renderUploadBadges(items: UploadItem[]) {
    return (
      <ul className="flex flex-col gap-1 text-sm">
        {items.map((item, index) => (
          <li key={`${item.file.name}-${index}`} className="flex items-center justify-between gap-3">
            <span className="truncate">{item.file.name}</span>
            {item.status === "pending" && (
              <span className="text-xs text-muted-foreground">Uploading…</span>
            )}
            {item.status === "success" && (
              <span className="text-xs font-medium text-green-700 dark:text-green-400">Uploaded</span>
            )}
            {item.status === "error" && (
              <span className="text-xs font-medium text-red-600 dark:text-red-400">
                Failed{item.error ? `: ${item.error}` : ""}
              </span>
            )}
          </li>
        ))}
      </ul>
    );
  }

  function renderIngestProgress() {
    if (!stalled && sseError && !done) {
      return <ErrorBanner message={sseError} />;
    }
    return <p className="text-sm text-muted-foreground">{formatJobProgress(job, stalled)}</p>;
  }

  const currentStep = currentStepFor(step);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Upload course"
        tabIndex={-1}
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg border border-border bg-surface-raised p-6 shadow-xl"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">Add a course</h2>
          <Button variant="secondary" size="sm" onClick={onClose} aria-label="Close">
            Close
          </Button>
        </div>

        <ol aria-label="Upload progress" className="mb-4 flex items-center gap-2 text-xs">
          {STEPS.map((label, i) => (
            <li key={label} className="flex items-center gap-2">
              <span
                aria-current={i === currentStep ? "step" : undefined}
                className={`flex h-5 w-5 items-center justify-center rounded-full text-[10px] font-semibold ${
                  i < currentStep
                    ? "bg-status-good-soft text-status-good"
                    : i === currentStep
                      ? "bg-accent text-white"
                      : "bg-muted-foreground/15 text-muted-foreground"
                }`}
              >
                {i < currentStep ? "✓" : i + 1}
              </span>
              <span className={i === currentStep ? "font-medium" : "text-muted-foreground"}>
                {label}
              </span>
              {i < STEPS.length - 1 && (
                <span aria-hidden="true" className="text-muted-foreground">
                  —
                </span>
              )}
            </li>
          ))}
        </ol>

        {step.kind === "title" && (
          <div className="flex flex-col gap-4">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground">Course title</span>
              <input
                type="text"
                value={step.title}
                onChange={(event) => setStep({ kind: "title", title: event.target.value })}
                className="rounded-md border border-border px-3 py-2"
              />
            </label>
            <ul className="text-sm text-muted-foreground">
              {files.map((file, index) => (
                <li key={`${file.name}-${index}`} className="truncate">
                  {file.name}
                </li>
              ))}
            </ul>
            <Button variant="primary" onClick={handleCreateCourse} className="self-end">
              Create &amp; upload
            </Button>
          </div>
        )}

        {step.kind === "creating" && (
          <p className="text-sm text-muted-foreground">Creating course…</p>
        )}

        {(step.kind === "uploading" || step.kind === "starting-ingest") && (
          <div className="flex flex-col gap-3">
            {renderUploadBadges(step.items)}
            <p className="text-sm text-muted-foreground">
              {step.kind === "uploading" ? "Uploading files…" : "Starting ingest…"}
            </p>
          </div>
        )}

        {step.kind === "ingesting" && (
          <div className="flex flex-col gap-3">
            {renderUploadBadges(step.items)}
            <div role="status">{renderIngestProgress()}</div>
          </div>
        )}

        {step.kind === "ingest-failed" && (
          <div className="flex flex-col gap-3">
            {renderUploadBadges(step.items)}
            <ErrorBanner message={step.message} onRetry={retryIngest} />
          </div>
        )}

        {step.kind === "fatal" && <ErrorBanner message={step.message} />}
      </div>
    </div>
  );
}
