"use client";

import { useEffect, useRef } from "react";

import { useJobEvents, type JobEvent } from "@/lib/hooks/useJobEvents";

export interface LessonJobWatcherProps {
  jobId: string;
  sectionId: string;
  onSettled: (sectionId: string, status: "ready" | "failed") => void;
  onUpdate?: (job: JobEvent) => void;
}

/**
 * Invisible: one instance per job_id in a generate_all_lessons batch, so
 * GenerateAllLessons can watch N jobs at once by rendering N of these
 * rather than needing a bespoke multi-job SSE hook — each just reuses the
 * existing single-job useJobEvents.
 */
export default function LessonJobWatcher({
  jobId,
  sectionId,
  onSettled,
  onUpdate,
}: LessonJobWatcherProps) {
  const { job, done } = useJobEvents(jobId);
  const settledRef = useRef(false);

  useEffect(() => {
    if (!job) return;
    onUpdate?.(job);
  }, [job, onUpdate]);

  useEffect(() => {
    if (!done || !job || settledRef.current) return;
    settledRef.current = true;
    onSettled(sectionId, job.status === "succeeded" ? "ready" : "failed");
  }, [done, job, sectionId, onSettled]);

  return null;
}
