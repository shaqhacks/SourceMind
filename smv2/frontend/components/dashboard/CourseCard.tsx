"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import ProgressBar from "@/components/ui/ProgressBar";
import {
  deleteCourse,
  exportCourseUrl,
  findActiveIngestJob,
  findLatestIngestJob,
  listAssets,
  startIngest,
  type AssetOut,
  type CourseOut,
} from "@/lib/api/client";
import { useContinueChapter } from "@/lib/dashboard/useContinueChapter";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { useSampleHintDismissed } from "@/lib/hooks/useSampleHint";
import { formatJobProgress } from "@/lib/jobs/format";

export interface CourseCardProps {
  course: CourseOut;
  onDeleted: (courseId: string) => void;
  onNeedsRefresh: () => void;
}

export default function CourseCard({ course, onDeleted, onNeedsRefresh }: CourseCardProps) {
  // Rediscovered/retried-job ids and the failure message are only
  // meaningful while the course is actually in that status — rather than
  // resetting them with a synchronous setState in an effect (a footgun:
  // it schedules an extra render every status change), they're derived
  // during render below and the raw state only ever gets written from
  // inside an async .then() callback.
  const [discoveredJobId, setDiscoveredJobId] = useState<string | null>(null);
  const [retriedJobId, setRetriedJobId] = useState<string | null>(null);
  const [discoveredFailureMessage, setDiscoveredFailureMessage] = useState<string | null>(null);
  const [failedAssets, setFailedAssets] = useState<AssetOut[]>([]);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [readyFailuresExpanded, setReadyFailuresExpanded] = useState(false);
  const [readyFailedAssets, setReadyFailedAssets] = useState<AssetOut[] | null>(null);
  const { dismissed: sampleHintDismissed, dismiss: dismissSampleHint } =
    useSampleHintDismissed(course.id);

  // A local retry always wins over the (possibly stale) `course.status`
  // prop — startIngest's own response already tells us a new job exists,
  // before the parent has had a chance to refetch and confirm it.
  const effectiveStatus = retriedJobId ? "ingesting" : course.status;
  const isIngesting = effectiveStatus === "ingesting";
  const jobId = retriedJobId ?? (isIngesting ? discoveredJobId : null);
  const failureMessage = effectiveStatus === "ingest_failed" ? discoveredFailureMessage : null;

  const { job, done, stalled } = useJobEvents(jobId);

  // Read-progress bar for a ready course the user has started — reuses the
  // same shared hook (one list_sections call) as ContinueCard/StatsRow. The
  // hook no-ops when there's no saved section, so a never-opened ready
  // course triggers no fetch.
  const readProgress = useContinueChapter(course.status === "ready" ? course : null);

  // "ingesting" courses have no job_id on CourseOut itself — rediscover
  // the active job by scanning the job list (see findActiveIngestJob's
  // own comment on why that's necessary).
  useEffect(() => {
    if (!isIngesting) return undefined;
    let active = true;
    findActiveIngestJob(course.id).then((found) => {
      if (active) setDiscoveredJobId(found?.id ?? null);
    });
    return () => {
      active = false;
    };
  }, [course.id, isIngesting]);

  // "ingest_failed": the failed job's own error message is the fallback
  // failure detail, shown only when no single asset can be pinned as the
  // cause (see the listAssets effect below, which is preferred when it
  // has something to show).
  useEffect(() => {
    if (course.status !== "ingest_failed") return undefined;
    let active = true;
    findLatestIngestJob(course.id).then((found) => {
      if (active) setDiscoveredFailureMessage(found?.error ?? "Ingest failed.");
    });
    return () => {
      active = false;
    };
  }, [course.id, course.status]);

  // Per-asset failure detail (filename + its own error) is more useful
  // than the job-level message when it's available — e.g. "chapter3.pdf:
  // password protected" pinpoints which upload to fix and re-try with.
  useEffect(() => {
    if (course.status !== "ingest_failed") return undefined;
    let active = true;
    listAssets(course.id).then(({ data }) => {
      if (!active || !data) return;
      setFailedAssets(data.filter((asset) => asset.status === "extract_failed"));
    });
    return () => {
      active = false;
    };
  }, [course.id, course.status]);

  // A "ready" course can still have per-item extraction failures (ingest
  // succeeds overall; a subset of assets don't). The count comes for free
  // on CourseOut, so no fetch is needed just to show the badge — the
  // per-asset detail is lazy, fetched only once the user expands it.
  useEffect(() => {
    if (!readyFailuresExpanded || readyFailedAssets !== null) return undefined;
    let active = true;
    listAssets(course.id).then(({ data }) => {
      if (!active || !data) return;
      setReadyFailedAssets(data.filter((asset) => asset.status === "extract_failed"));
    });
    return () => {
      active = false;
    };
  }, [readyFailuresExpanded, readyFailedAssets, course.id]);

  // Once the job we're watching (rediscovered or freshly retried) reaches
  // a terminal status, this card's `course` prop is stale (status/
  // section_count changed server-side) — ask the parent to refetch rather
  // than guessing the new values locally.
  useEffect(() => {
    if (done) onNeedsRefresh();
  }, [done, onNeedsRefresh]);

  async function handleDelete() {
    setDeleting(true);
    const { ok } = await deleteCourse(course.id);
    setDeleting(false);
    if (ok) onDeleted(course.id);
  }

  async function handleRetryIngest() {
    setRetrying(true);
    const { data } = await startIngest(course.id);
    setRetrying(false);
    if (data) setRetriedJobId(data.job_id);
  }

  return (
    <Card className="flex flex-col gap-2">
      <div className="flex items-start justify-between gap-3">
        <h3 className="truncate text-sm font-semibold">
          {course.status === "ready" ? (
            <Link href={`/course/${course.id}`} className="underline-offset-2 hover:underline">
              {course.title}
            </Link>
          ) : (
            course.title
          )}
        </h3>
        {course.status === "ready" && <Badge tone="good">Ready</Badge>}
        {course.status === "draft" && <Badge tone="neutral">Draft</Badge>}
      </div>

      {course.is_sample && !sampleHintDismissed && (
        <div
          role="note"
          className="flex items-center justify-between gap-3 rounded-md border border-border bg-accent/5 px-3 py-2 text-xs"
        >
          <span>This is a sample course — drop your own file to create a course.</span>
          <button
            type="button"
            onClick={dismissSampleHint}
            aria-label="Dismiss hint"
            className="shrink-0 rounded-md border border-border px-2 py-1 font-medium"
          >
            Dismiss
          </button>
        </div>
      )}

      {isIngesting && (
        <div role="status" className="text-xs text-muted-foreground">
          <span>{formatJobProgress(job, stalled)}</span>
        </div>
      )}

      {course.status === "ready" && course.failed_asset_count > 0 && (
        <div className="flex flex-col gap-1">
          <button
            type="button"
            onClick={() => setReadyFailuresExpanded((value) => !value)}
            aria-expanded={readyFailuresExpanded}
            className="self-start"
          >
            <Badge tone="warning">
              {course.failed_asset_count} file{course.failed_asset_count === 1 ? "" : "s"} failed
              extraction
            </Badge>
          </button>
          {readyFailuresExpanded &&
            (readyFailedAssets === null ? (
              <p className="text-xs text-muted-foreground">Loading…</p>
            ) : (
              <ul className="flex flex-col gap-1">
                {readyFailedAssets.map((asset) => (
                  <li key={asset.id}>
                    <Badge tone="serious">
                      {asset.filename}
                      {asset.error ? `: ${asset.error}` : ""}
                    </Badge>
                  </li>
                ))}
              </ul>
            ))}
        </div>
      )}

      {effectiveStatus === "ingest_failed" && (
        <div className="flex flex-col gap-2">
          {failedAssets.length > 0 ? (
            <ul className="flex flex-col gap-1">
              {failedAssets.map((asset) => (
                <li key={asset.id}>
                  <Badge tone="serious">
                    {asset.filename}
                    {asset.error ? `: ${asset.error}` : ""}
                  </Badge>
                </li>
              ))}
            </ul>
          ) : (
            <Badge tone="serious">{failureMessage ?? "Ingest failed"}</Badge>
          )}
          <Button size="sm" onClick={handleRetryIngest} disabled={retrying} className="self-start">
            {retrying ? "Retrying…" : "Retry ingest"}
          </Button>
        </div>
      )}

      {readProgress && (
        <ProgressBar percent={readProgress.percent} label={`Progress through ${course.title}`} />
      )}

      <div className="mt-auto flex items-center justify-between pt-2">
        {course.status === "ready" ? (
          <a href={exportCourseUrl(course.id)} download className="text-xs font-medium text-accent">
            Export
          </a>
        ) : (
          <span />
        )}

        {confirmingDelete ? (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">Delete this course?</span>
            <Button variant="danger" size="sm" onClick={handleDelete} disabled={deleting}>
              {deleting ? "Deleting…" : "Confirm"}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirmingDelete(false)}>
              Cancel
            </Button>
          </div>
        ) : (
          <Button variant="danger" size="sm" onClick={() => setConfirmingDelete(true)}>
            Delete
          </Button>
        )}
      </div>
    </Card>
  );
}
