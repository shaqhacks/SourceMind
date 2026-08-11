"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import GenerationProgress from "@/components/jobs/GenerationProgress";
import RecoveryBanner from "@/components/RecoveryBanner";
import Button from "@/components/ui/Button";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  generateTest,
  listJobs,
  listTests,
  TERMINAL_JOB_STATUSES,
  type TestSummaryOut,
} from "@/lib/api/client";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { useJobFailure } from "@/lib/hooks/useJobFailureMessage";
import { cancelGenerationJob } from "@/lib/jobs/cancel";

import { findActiveChapterTestJob } from "./testsFormat";

export interface GenerateTestCardProps {
  courseId: string;
  chapterLabel: string;
  /** This chapter's tests as of the last parent fetch — snapshot of known
   * attempt ids, so a successful generation can tell which fresh attempt
   * to navigate into (generate_test's own response is just a job_id). */
  existingTests: TestSummaryOut[];
  onSettled: () => void;
}

const QUESTION_COUNT = 8;

/** Dashed "not attempted" card: starts a chapter-scoped generate_test job
 * (mirrors ChapterTestClient's own generate flow) and, on success, jumps
 * straight into the freshly-created attempt — generating a chapter test
 * implies "I want to take it now", same precedent as the chapter test page. */
export default function GenerateTestCard({
  courseId,
  chapterLabel,
  existingTests,
  onSettled,
}: GenerateTestCardProps) {
  const router = useRouter();
  const [localJobId, setLocalJobId] = useState<string | null>(null);
  const [discoveredJobId, setDiscoveredJobId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<FetchError | null>(null);
  const knownAttemptIdsRef = useRef<Set<string>>(new Set());
  // Guards the job-succeeded effect below against re-firing for the SAME
  // job: `onSettled` is a fresh closure every render of the parent
  // (`onSettled={() => loadChapters(selectedCourseId)}`) and `courseId` can
  // also change identity across a parent re-render, so this effect's own
  // dependency array churns independently of `done`/`job?.status` actually
  // changing — without this guard, a re-run after the job already succeeded
  // would call listTests/onSettled/router.push again for a job that already
  // finished being handled.
  const handledJobIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (localJobId) return undefined;
    let active = true;
    listJobs().then(({ data }) => {
      if (!active || !data) return;
      const found = findActiveChapterTestJob(data, courseId, chapterLabel, TERMINAL_JOB_STATUSES);
      setDiscoveredJobId(found?.id ?? null);
    });
    return () => {
      active = false;
    };
  }, [courseId, chapterLabel, localJobId]);

  const watchedJobId = localJobId ?? discoveredJobId;
  const { job, done, stalled } = useJobEvents(watchedJobId);
  const isGenerating = watchedJobId !== null && !done;
  const jobFailed = done && job?.status === "failed";
  const failureInfo = useJobFailure(jobFailed, watchedJobId);

  useEffect(() => {
    if (!done || job?.status !== "succeeded" || !watchedJobId) return;
    if (handledJobIdRef.current === watchedJobId) return;
    handledJobIdRef.current = watchedJobId;
    listTests(courseId).then(({ data }) => {
      if (!data) return;
      const forChapter = data.filter((test) => test.chapter_label === chapterLabel);
      const freshAttempt = forChapter
        .flatMap((test) => test.attempts)
        .find((attempt) => !knownAttemptIdsRef.current.has(attempt.id));
      onSettled();
      if (freshAttempt) router.push(`/course/${courseId}/test/${freshAttempt.id}`);
    });
  }, [done, job?.status, watchedJobId, courseId, chapterLabel, router, onSettled]);

  async function handleGenerate() {
    setStarting(true);
    setStartError(null);
    knownAttemptIdsRef.current = new Set(
      existingTests.flatMap((test) => test.attempts.map((attempt) => attempt.id)),
    );
    const { data, status, error } = await generateTest(courseId, { chapterLabel });
    setStarting(false);
    if (data) {
      setLocalJobId(data.job_id);
      return;
    }
    setStartError(describeError(status, "Starting test generation", error));
  }

  return (
    <div className="flex flex-col gap-2.5 rounded-lg border-[1.5px] border-dashed border-neutral-400 bg-transparent p-5">
      <span className="text-xs font-semibold uppercase tracking-wide text-neutral-600">
        {chapterLabel}
      </span>
      <p className="text-sm text-muted-foreground">
        Not attempted yet — generate a {QUESTION_COUNT}-question test from this chapter.
      </p>
      {jobFailed && (
        <RecoveryBanner
          message={`Generation failed${failureInfo.message ? `: ${failureInfo.message}` : "."}`}
          onRetry={() => void handleGenerate()}
          jobId={watchedJobId}
          errorDetail={failureInfo.detail}
        />
      )}
      {isGenerating ? (
        <GenerationProgress
          job={stalled ? null : job}
          quiet={stalled}
          compact
          onCancel={watchedJobId ? () => cancelGenerationJob(watchedJobId) : undefined}
          onContinue={() => router.push(`/course/${courseId}`)}
        />
      ) : (
        !jobFailed && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void handleGenerate()}
            disabled={starting}
            className="self-start"
          >
            Generate test
          </Button>
        )
      )}
      {startError && (
        <RecoveryBanner
          message={startError.message}
          errorDetail={startError.detail}
          onRetry={() => void handleGenerate()}
        />
      )}
    </div>
  );
}
