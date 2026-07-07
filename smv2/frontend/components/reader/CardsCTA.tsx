"use client";

import { useEffect, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  findActiveCardsJob,
  generateCards,
  getJob,
  listCards,
  type CardOut,
} from "@/lib/api/client";
import { notifyCardsSettled } from "@/lib/cards/cardsBus";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { formatJobProgress } from "@/lib/jobs/format";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

export interface CardsCTAProps {
  sectionId: string;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "loaded"; cards: CardOut[] };

async function fetchCards(sectionId: string): Promise<LoadState> {
  const { data, status } = await listCards(sectionId);
  if (!data) return { kind: "error", error: describeError(status, "Loading flashcards") };
  return { kind: "loaded", cards: data };
}

/**
 * "Generate flashcards" per section, mirroring LessonPane's job-lifecycle
 * pattern (mount-time rediscovery of an in-flight job, SSE progress,
 * refetch-on-settle, 409 resync instead of an error). No estimate/confirm
 * step — card generation doesn't have per-request cost preview like lesson
 * generation does.
 */
export default function CardsCTA({ sectionId }: CardsCTAProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [localJobId, setLocalJobId] = useState<string | null>(null);
  const [discoveredJobId, setDiscoveredJobId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  // Tagged with the jobId it was fetched for (same idiom as useJobEvents'
  // own internal state) so staleness is a render-time comparison rather
  // than something an effect has to reset — a plain top-of-effect
  // setState would fire on every dependency change, not just the fetch.
  const [failureInfo, setFailureInfo] = useState<{ jobId: string; message: string | null } | null>(
    null,
  );

  useEffect(() => {
    let active = true;
    fetchCards(sectionId).then((result) => {
      if (active) setState(result);
    });
    return () => {
      active = false;
    };
  }, [sectionId]);

  // Rediscover a job already in flight (from a prior session), unless we
  // just started one ourselves this session.
  useEffect(() => {
    if (localJobId) return undefined;
    let active = true;
    findActiveCardsJob(sectionId).then((found) => {
      if (active) setDiscoveredJobId(found?.id ?? null);
    });
    return () => {
      active = false;
    };
  }, [sectionId, localJobId]);

  const watchedJobId = localJobId ?? discoveredJobId;
  const { job, done, stalled } = useJobEvents(watchedJobId);
  const isGenerating = watchedJobId !== null && !done;
  const jobFailed = done && job?.status === "failed";
  const failureMessage = failureInfo?.jobId === watchedJobId ? failureInfo.message : null;

  useEffect(() => {
    if (!done) return;
    fetchCards(sectionId).then(setState);
    notifyReviewSettled();
    // Tells SectionCards (rendered as a sibling below this CTA) to
    // refetch and show the fresh cards right there — the whole point of
    // this signal is "generate -> cards appear immediately", so it fires
    // regardless of whether the job succeeded or failed (a failed job
    // just means the refetch reconfirms the same list).
    notifyCardsSettled(sectionId);
  }, [done, sectionId]);

  // JobEvent (the SSE snapshot) carries no error text — only {id, status,
  // progress} — so surfacing the actual failure message needs a follow-up
  // plain REST fetch, same as UploadFlow does for a failed ingest job.
  useEffect(() => {
    if (!jobFailed || !watchedJobId) return;
    let active = true;
    getJob(watchedJobId).then(({ data }) => {
      if (active) setFailureInfo({ jobId: watchedJobId, message: data?.error ?? null });
    });
    return () => {
      active = false;
    };
  }, [jobFailed, watchedJobId]);

  async function handleGenerate() {
    setActionError(null);
    const { data, status } = await generateCards(sectionId);
    if (data) {
      setLocalJobId(data.job_id);
      return;
    }
    if (status === 409) {
      // Already in progress somewhere else — resync rather than error.
      const found = await findActiveCardsJob(sectionId);
      setDiscoveredJobId(found?.id ?? null);
      return;
    }
    setActionError(describeError(status, "Starting flashcard generation").message);
  }

  if (state.kind === "loading") {
    return (
      <p role="status" className="text-xs text-muted-foreground">
        Loading flashcards…
      </p>
    );
  }

  if (state.kind === "error") {
    return <p className="text-xs text-red-600 dark:text-red-400">{state.error.message}</p>;
  }

  if (isGenerating) {
    return (
      <p role="status" className="text-xs text-muted-foreground">
        {formatJobProgress(job, stalled)}
      </p>
    );
  }

  if (jobFailed) {
    return (
      <ErrorBanner
        message={`Generation failed${failureMessage ? `: ${failureMessage}` : "."}`}
        onRetry={() => void handleGenerate()}
      />
    );
  }

  return (
    <div className="flex items-center gap-2 text-xs">
      {state.cards.length > 0 && (
        <span className="text-muted-foreground">
          {state.cards.length} flashcard{state.cards.length === 1 ? "" : "s"}
        </span>
      )}
      <button
        type="button"
        onClick={() => void handleGenerate()}
        className="rounded-md border border-border px-2 py-1 font-medium"
      >
        {state.cards.length > 0 ? "Generate more flashcards" : "Generate flashcards"}
      </button>
      {actionError && <span className="text-red-600 dark:text-red-400">{actionError}</span>}
    </div>
  );
}
