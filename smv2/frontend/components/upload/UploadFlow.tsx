"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import ErrorBanner from "@/components/ErrorBanner";
import OutlineConfirmation from "@/components/upload/OutlineConfirmation";
import {
  createCourse,
  editOutline,
  getJob,
  listSections,
  startIngest,
  uploadAsset,
  type OutlineOp,
  type SectionOut,
} from "@/lib/api/client";
import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";

export interface UploadFlowProps {
  files: File[];
  onClose: () => void;
}

interface UploadItem {
  file: File;
  status: "pending" | "success" | "error";
  error?: string;
}

function defaultTitleFromFilename(name: string): string {
  const withoutExtension = name.replace(/\.[^./]+$/, "");
  const spaced = withoutExtension.replace(/[_-]+/g, " ").trim();
  return spaced || "Untitled course";
}

type Step =
  | { kind: "title"; title: string }
  | { kind: "creating" }
  | { kind: "uploading"; courseId: string; items: UploadItem[] }
  | { kind: "starting-ingest"; courseId: string; items: UploadItem[] }
  | { kind: "ingesting"; courseId: string; jobId: string; items: UploadItem[] }
  | { kind: "ingest-failed"; courseId: string; items: UploadItem[]; message: string }
  | { kind: "confirming"; courseId: string; sections: SectionOut[] }
  | { kind: "applying"; courseId: string }
  | { kind: "fatal"; message: string };

function describeApiError(status: number | undefined, action: string): string {
  return status === undefined
    ? `${action}: could not reach the API. Is the backend running?`
    : `${action} failed (HTTP ${status}).`;
}

/**
 * Modal walking a freshly-selected/dropped batch of PDFs through: create
 * course -> upload each file (independently — one failure doesn't stop the
 * rest) -> start_ingest -> live SSE progress -> outline confirmation ->
 * (optional) one edit_outline PATCH -> navigate into the reader.
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
            : { file, status: "error", error: describeApiError(status, "Upload") };
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
          message: describeApiError(ingestStatus, "Starting ingest"),
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
      setStep({ kind: "fatal", message: describeApiError(status, "Creating the course") });
      return;
    }

    await runUploadsAndIngest(data.id);
  }, [step, runUploadsAndIngest]);

  const retryIngest = useCallback(() => {
    if (step.kind !== "ingest-failed") return;
    void runUploadsAndIngest(step.courseId);
  }, [step, runUploadsAndIngest]);

  // Ingest job succeeded: fetch the detected outline for review.
  useEffect(() => {
    if (!done || !job || job.status !== "succeeded" || step.kind !== "ingesting") return;
    const courseId = step.courseId;
    let active = true;
    listSections(courseId).then(({ data }) => {
      if (!active) return;
      setStep({ kind: "confirming", courseId, sections: data ?? [] });
    });
    return () => {
      active = false;
    };
  }, [done, job, step]);

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

  const handleAcceptOutline = useCallback(
    async (operations: OutlineOp[]) => {
      if (step.kind !== "confirming") return;
      const courseId = step.courseId;
      if (operations.length > 0) {
        setStep({ kind: "applying", courseId });
        const { data } = await editOutline(courseId, operations);
        if (!data) {
          setStep({ kind: "fatal", message: "Applying your outline edits failed." });
          return;
        }
      }
      router.push(`/course/${courseId}`);
    },
    [step, router],
  );

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
    if (stalled) {
      return (
        <p className="text-sm text-muted-foreground">
          Still working — check back shortly.
        </p>
      );
    }
    if (sseError && !done) {
      return <ErrorBanner message={sseError} />;
    }
    if (!job || !job.progress) {
      return <p className="text-sm text-muted-foreground">Preparing…</p>;
    }
    return (
      <p className="text-sm text-muted-foreground">
        {job.progress.stage} — {job.progress.pct}% — {job.progress.message}
      </p>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Upload course"
        tabIndex={-1}
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg border border-border bg-background p-6 shadow-xl"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">Add a course</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md border border-border px-2 py-1 text-sm"
          >
            Close
          </button>
        </div>

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
            <button
              type="button"
              onClick={handleCreateCourse}
              className="self-end rounded-md bg-black px-4 py-2 text-sm font-medium text-white dark:bg-white dark:text-black"
            >
              Create &amp; upload
            </button>
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

        {step.kind === "confirming" && (
          <OutlineConfirmation sections={step.sections} onAccept={handleAcceptOutline} />
        )}

        {step.kind === "applying" && (
          <p className="text-sm text-muted-foreground">Applying your outline edits…</p>
        )}

        {step.kind === "fatal" && <ErrorBanner message={step.message} />}
      </div>
    </div>
  );
}
