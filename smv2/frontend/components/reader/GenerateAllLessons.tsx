"use client";

import { useCallback, useState } from "react";

import { generateAllLessons, getJob } from "@/lib/api/client";
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
  const [error, setError] = useState<string | null>(null);

  const total = watchList?.length ?? 0;
  const inProgress = watchList !== null && settledCount < total;

  const handleStart = useCallback(async () => {
    setStarting(true);
    setError(null);
    const { data, status } = await generateAllLessons(courseId);
    setStarting(false);

    if (!data) {
      setError(
        status === undefined
          ? "Could not reach the API."
          : `Starting generation failed (HTTP ${status}).`,
      );
      return;
    }

    setSkipped(data.skipped);
    setSettledCount(0);

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

  const handleSettled = useCallback(
    (sectionId: string, status: "ready" | "failed") => {
      setSettledCount((count) => count + 1);
      onSectionSettled(sectionId, status);
      notifyReviewSettled();
    },
    [onSectionSettled],
  );

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => void handleStart()}
        disabled={starting || inProgress}
        className="rounded-md border border-border px-3 py-1.5 text-sm font-medium disabled:opacity-50"
      >
        {inProgress ? `Generating ${settledCount} of ${total}…` : "Generate all lessons"}
      </button>
      {error && <span className="text-xs text-red-600 dark:text-red-400">{error}</span>}
      {!inProgress && watchList !== null && skipped > 0 && (
        <span className="text-xs text-muted-foreground">{skipped} already generated</span>
      )}
      {watchList?.map((entry) => (
        <LessonJobWatcher
          key={entry.jobId}
          jobId={entry.jobId}
          sectionId={entry.sectionId}
          onSettled={handleSettled}
        />
      ))}
    </div>
  );
}
