"use client";

import { useEffect, useState } from "react";

import { findActiveCardsJob, generateCards, listCards, type CardOut } from "@/lib/api/client";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

export interface CardsCTAProps {
  sectionId: string;
}

interface FetchError {
  status?: number;
  message: string;
}

function describeError(status: number | undefined, action: string): FetchError {
  if (status === undefined) {
    return { message: `${action}: could not reach the API. Is the backend running?` };
  }
  return { status, message: `${action} failed (HTTP ${status}).` };
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

  useEffect(() => {
    if (!done) return;
    fetchCards(sectionId).then(setState);
    notifyReviewSettled();
  }, [done, sectionId]);

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
        {stalled
          ? "Still working — check back shortly."
          : job?.progress
            ? `${job.progress.stage} — ${job.progress.pct}% — ${job.progress.message}`
            : "Preparing…"}
      </p>
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
