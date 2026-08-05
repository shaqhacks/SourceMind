"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { X } from "lucide-react";

import ErrorBanner from "@/components/ErrorBanner";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import OutlineConfirmation from "@/components/upload/OutlineConfirmation";
import { describeError } from "@/lib/api/errors";
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
import { useDismissOnOutsideOrEscape } from "@/lib/hooks/useDismissOnOutsideOrEscape";
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
  pageCount?: number | null;
}

type Step =
  | { kind: "title"; title: string }
  | { kind: "creating" }
  | { kind: "uploading"; courseId: string; items: UploadItem[] }
  | { kind: "starting-ingest"; courseId: string; items: UploadItem[] }
  | { kind: "ingesting"; courseId: string; jobId: string; items: UploadItem[] }
  | { kind: "ingest-failed"; courseId: string; items: UploadItem[]; message: string }
  | { kind: "loading-outline"; courseId: string; items: UploadItem[] }
  | { kind: "outline-load-failed"; courseId: string; items: UploadItem[]; message: string }
  | { kind: "confirming-outline"; courseId: string; items: UploadItem[]; sections: SectionOut[] }
  | { kind: "fatal"; message: string };

const STEPS = ["Upload", "Confirm outline", "Start reading"] as const;

/**
 * Maps the state machine above onto the 3-step "Upload -> Confirm outline
 * -> Start reading" indicator (redesign handoff section 9). Everything from
 * naming the course through a finished ingest is still "Upload" — course
 * creation, per-file upload, and the ingest job are all part of turning the
 * dropped files into a readable outline, not steps a user perceives
 * separately. "Start reading" never lights up as the *current* step: it
 * completes the instant accept navigates away.
 */
function currentStepFor(step: Step): 0 | 1 | 2 {
  switch (step.kind) {
    case "title":
    case "creating":
    case "uploading":
    case "starting-ingest":
    case "ingesting":
    case "ingest-failed":
    case "loading-outline":
    case "outline-load-failed":
    case "fatal":
      return 0;
    case "confirming-outline":
      return 1;
  }
}

/**
 * "Start a new course" dialog: create course -> upload each file
 * (independently — one failure doesn't stop the rest) -> start_ingest ->
 * live SSE progress -> fetch the detected outline -> confirm/edit it ->
 * straight into the reader. Outline confirmation returns here as an
 * explicit step per the redesign (README section 9) — reversing ADR-014
 * (docs/decisions.md), which had removed it in favor of reader-only
 * editing. The reader's "Edit outline" / "o" shortcut (OutlineEditorModal)
 * is unaffected and still works against the live course afterward.
 */
export default function UploadFlow({ files, onClose }: UploadFlowProps) {
  const router = useRouter();
  const [step, setStep] = useState<Step>({
    kind: "title",
    title: defaultTitleFromFilename(files[0]?.name ?? ""),
  });
  const [applyingOutline, setApplyingOutline] = useState(false);
  const [outlineApplyError, setOutlineApplyError] = useState<string | null>(null);

  // This modal is mounted/unmounted by the parent (no internal open/close
  // toggle), so "open" is just "true" for its whole lifetime — the hooks'
  // close-focus-restore/listener-teardown fire naturally on unmount.
  const dialogRef = useDialogFocus<HTMLDivElement>(true);
  // An (intentionally empty) scope still occupies the top of the shared
  // shortcut-scope stack while mounted — this is what stops the page
  // underneath from also firing its own shortcuts. Escape is handled
  // independently via useDismissOnOutsideOrEscape's own document listener,
  // not through this stack: OutlineConfirmation (a descendant, mounted only
  // once the outline loads) registers its own "Enter accepts" scope, which
  // ends up ON TOP of this one and would silently shadow an "escape"
  // handler placed here instead. Same pattern as OutlineEditorModal.
  useKeyboardShortcuts({}, true);
  useDismissOnOutsideOrEscape(true, onClose, dialogRef);

  const activeJobId = step.kind === "ingesting" ? step.jobId : null;
  const { job, error: sseError, done, stalled } = useJobEvents(activeJobId);

  const runUploadsAndIngest = useCallback(
    async (courseId: string) => {
      const initialItems: UploadItem[] = files.map((file) => ({ file, status: "pending" }));
      setStep({ kind: "uploading", courseId, items: initialItems });

      const settled = await Promise.all(
        files.map(async (file, index) => {
          const { data, status, error } = await uploadAsset(courseId, file);
          const result: UploadItem = data
            ? { file, status: "success", pageCount: data.page_count }
            : { file, status: "error", error: describeError(status, "Upload", error).message };
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

  const handleOutlineAccept = useCallback(
    async (courseId: string, operations: OutlineOp[]) => {
      if (operations.length === 0) {
        router.push(`/course/${courseId}`);
        return;
      }
      setApplyingOutline(true);
      setOutlineApplyError(null);
      const { data } = await editOutline(courseId, operations);
      setApplyingOutline(false);
      if (!data) {
        setOutlineApplyError("Applying your outline edits failed.");
        return;
      }
      router.push(`/course/${courseId}`);
    },
    [router],
  );

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

  // Ingest job succeeded → fetch the detected outline for confirmation,
  // rather than navigating straight in (see this component's doc comment).
  // The step deliberately STAYS "ingesting" while this fetch runs (the
  // render below shows the loading line for that combination) so the
  // transition happens inside .then(), never synchronously in the effect
  // body (react-hooks/set-state-in-effect). "loading-outline" as a step
  // kind is only entered from the outline-load-failed Retry handler.
  useEffect(() => {
    if (step.kind !== "loading-outline" && step.kind !== "ingesting") return;
    if (step.kind === "ingesting" && !(done && job?.status === "succeeded")) return;
    const courseId = step.courseId;
    const items = step.items;
    let active = true;
    listSections(courseId).then(({ data, status }) => {
      if (!active) return;
      if (data) {
        setStep({ kind: "confirming-outline", courseId, items, sections: data });
      } else {
        setStep({
          kind: "outline-load-failed",
          courseId,
          items,
          message: describeError(status, "Loading the detected outline").message,
        });
      }
    });
    return () => {
      active = false;
    };
  }, [step, done, job]);

  function renderFileRows(items: UploadItem[]) {
    return (
      <ul className="flex flex-col gap-2">
        {items.map((item, index) => (
          <li
            key={`${item.file.name}-${index}`}
            className="flex items-center gap-3 rounded-md border border-divider bg-background px-4 py-3"
          >
            <span className="min-w-0 flex-1 truncate text-sm font-medium">{item.file.name}</span>
            {item.status === "pending" && (
              <span className="shrink-0 text-xs text-muted-foreground">Uploading…</span>
            )}
            {item.status === "success" && (
              <Badge tone="good">
                Uploaded{item.pageCount != null ? ` · ${item.pageCount} pages` : ""}
              </Badge>
            )}
            {item.status === "error" && (
              <Badge tone="serious">Failed{item.error ? `: ${item.error}` : ""}</Badge>
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-neutral-900/50 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Start a new course"
        tabIndex={-1}
        className="flex max-h-[90vh] w-[620px] max-w-full flex-col gap-5 overflow-y-auto rounded-lg border border-divider bg-surface-raised p-7 shadow-lg"
      >
        <div className="flex items-center justify-between">
          <h2 className="font-heading text-xl">Start a new course</h2>
          <Button variant="secondary" size="sm" onClick={onClose} aria-label="Close">
            <X className="h-4 w-4" strokeWidth={2.75} />
          </Button>
        </div>

        <ol aria-label="Upload progress" className="flex items-center gap-2 text-xs font-semibold">
          {STEPS.map((label, i) => (
            <li
              key={label}
              className={`flex flex-1 items-center gap-2 last:flex-none ${
                i < currentStep
                  ? "text-sage-700"
                  : i === currentStep
                    ? "text-accent-700"
                    : "text-neutral-600"
              }`}
            >
              <span
                aria-current={i === currentStep ? "step" : undefined}
                className={`flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full text-[12px] ${
                  i < currentStep
                    ? "bg-sage-500 text-background"
                    : i === currentStep
                      ? "bg-accent-700 text-background"
                      : "bg-neutral-200"
                }`}
              >
                {i < currentStep ? "✓" : i + 1}
              </span>
              <span>{label}</span>
              {i < STEPS.length - 1 && (
                <span
                  aria-hidden="true"
                  className={`h-[2px] flex-1 ${i < currentStep ? "bg-sage-400" : "bg-neutral-300"}`}
                />
              )}
            </li>
          ))}
        </ol>

        {step.kind === "title" && (
          <div className="flex flex-col gap-4">
            {files.length > 0 && (
              <ul className="flex flex-col gap-2">
                {files.map((file, index) => (
                  <li
                    key={`${file.name}-${index}`}
                    className="truncate rounded-md border border-divider bg-background px-4 py-3 text-sm font-medium"
                  >
                    {file.name}
                  </li>
                ))}
              </ul>
            )}
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-muted-foreground">Course title</span>
              <input
                type="text"
                value={step.title}
                onChange={(event) => setStep({ kind: "title", title: event.target.value })}
                className="rounded-md border border-border bg-surface-raised px-3.5 py-2 focus-visible:border-accent"
              />
            </label>
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
            {renderFileRows(step.items)}
            <p className="text-sm text-muted-foreground">
              {step.kind === "uploading" ? "Uploading files…" : "Starting ingest…"}
            </p>
          </div>
        )}

        {step.kind === "ingesting" && !(done && job?.status === "succeeded") && (
          <div className="flex flex-col gap-3">
            {renderFileRows(step.items)}
            <div role="status">{renderIngestProgress()}</div>
          </div>
        )}

        {step.kind === "ingest-failed" && (
          <div className="flex flex-col gap-3">
            {renderFileRows(step.items)}
            <ErrorBanner message={step.message} onRetry={retryIngest} />
          </div>
        )}

        {(step.kind === "loading-outline" ||
          (step.kind === "ingesting" && done && job?.status === "succeeded")) && (
          <div className="flex flex-col gap-3">
            {renderFileRows(step.items)}
            <p role="status" className="text-sm text-muted-foreground">
              Loading detected outline…
            </p>
          </div>
        )}

        {step.kind === "outline-load-failed" && (
          <div className="flex flex-col gap-3">
            {renderFileRows(step.items)}
            <ErrorBanner
              message={step.message}
              onRetry={() =>
                setStep({ kind: "loading-outline", courseId: step.courseId, items: step.items })
              }
            />
          </div>
        )}

        {step.kind === "confirming-outline" && (
          <div className="flex flex-col gap-4">
            {renderFileRows(step.items)}
            {outlineApplyError && <ErrorBanner message={outlineApplyError} />}
            {applyingOutline && (
              <p role="status" className="text-sm text-muted-foreground">
                Saving your outline…
              </p>
            )}
            <OutlineConfirmation
              sections={step.sections}
              heading={`Detected outline — ${step.sections.length} chapter${
                step.sections.length === 1 ? "" : "s"
              }`}
              description="No AI used · instant & free"
              submitLabel="Accept outline & start reading"
              reassuranceNote="You can fix the outline any time from the reader — merging or splitting resets review state for affected chapters only."
              onCancel={onClose}
              onAccept={(operations) => handleOutlineAccept(step.courseId, operations)}
            />
          </div>
        )}

        {step.kind === "fatal" && <ErrorBanner message={step.message} />}
      </div>
    </div>
  );
}
