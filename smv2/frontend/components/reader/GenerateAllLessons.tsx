"use client";

import { useCallback, useState } from "react";

import GenerationProgress from "@/components/jobs/GenerationProgress";
import RecoveryBanner from "@/components/RecoveryBanner";
import Button from "@/components/ui/Button";
import { generateAllLessons, getJob } from "@/lib/api/client";
import { describeError, type FetchError } from "@/lib/api/errors";
import type { JobEvent } from "@/lib/hooks/useJobEvents";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

import LessonJobWatcher from "./LessonJobWatcher";

export interface GenerateAllLessonsProps {
  courseId: string;
  onSectionSettled: (sectionId: string, status: "ready" | "failed") => void;
}

interface WatchEntry {
  jobId: string;
  sectionId: string;
}

function extractSectionId(payload: { [key: string]: unknown } | null | undefined): string | null {
  return payload && typeof payload.section_id === "string" ? payload.section_id : null;
}

/**
 * generate_all_lessons returns only job_ids (no section mapping), so each
 * job is looked up once via getJob to learn its payload.section_id before
 * watching it — that's the only way to know which sidebar dot a given
 * job's completion should patch.
 */
export default function GenerateAllLessons({ courseId, onSectionSettled }: GenerateAllLessonsProps) {
  const [watchList, setWatchList] = useState<WatchEntry[] | null>(null);
  const [settledCount, setSettledCount] = useState(0);
  const [skipped, setSkipped] = useState(0);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<FetchError | null>(null);
  const [jobEvents, setJobEvents] = useState<Record<string, JobEvent>>({});

  const total = watchList?.length ?? 0;
  const inProgress = watchList !== null && settledCount < total;
  const representativeJob =
    watchList
      ?.map((entry) => jobEvents[entry.jobId])
      .find((job) => job && job.status !== "succeeded" && job.status !== "failed" && job.status !== "cancelled") ??
    null;

  const handleStart = useCallback(async () => {
    setStarting(true);
    setError(null);
    const { data, status, error } = await generateAllLessons(courseId);
    setStarting(false);

    if (!data) {
      setError(describeError(status, "Starting generation", error));
      return;
    }

    setSkipped(data.skipped);
    setSettledCount(0);
    setJobEvents({});

    if (data.job_ids.length === 0) {
      setWatchList([]);
      return;
    }

    const jobs = await Promise.all(data.job_ids.map((jobId) => getJob(jobId)));
    const entries: WatchEntry[] = [];
    jobs.forEach((result, index) => {
      const sectionId = extractSectionId(result.data?.payload);
      if (sectionId) entries.push({ jobId: data.job_ids[index], sectionId });
    });
    setWatchList(entries);
  }, [courseId]);

  const handleSettled = useCallback(() => {
    setSettledCount((count) => count + 1);
  }, []);

  const handleSectionSettled = useCallback(
    (sectionId: string, status: "ready" | "failed") => {
      onSectionSettled(sectionId, status);
      notifyReviewSettled();
    },
    [onSectionSettled],
  );

  const handleJobUpdate = useCallback((job: JobEvent) => {
    setJobEvents((current) => ({ ...current, [job.id]: job }));
  }, []);

  return (
    <div className="flex items-center gap-2">
      <Button
        variant="toolbar"
        size="toolbar"
        onClick={() => void handleStart()}
        disabled={starting || inProgress}
        aria-live="polite"
        className="font-medium"
      >
        {inProgress ? "Generating lessons" : "Generate all lessons"}
      </Button>
      {inProgress && (
        <div className="min-w-72">
          <GenerationProgress job={representativeJob} quiet={settledCount > 0} compact />
          <p className="mt-1 text-xs text-muted-foreground">
            {settledCount} of {total} lesson jobs settled.
          </p>
        </div>
      )}
      {error && (
        <div className="min-w-72">
          <RecoveryBanner
            message={error.message}
            errorDetail={error.detail}
            onRetry={() => void handleStart()}
          />
        </div>
      )}
      {!inProgress && watchList !== null && skipped > 0 && (
        <span className="text-xs text-muted-foreground">{skipped} already generated</span>
      )}
      {watchList?.map((entry) => (
        <LessonJobWatcher
          key={entry.jobId}
          jobId={entry.jobId}
          sectionId={entry.sectionId}
          onSettled={handleSettled}
          onSectionSettled={handleSectionSettled}
          onUpdate={handleJobUpdate}
        />
      ))}
    </div>
  );
}
