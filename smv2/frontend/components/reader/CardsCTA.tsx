"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import GenerationProgress from "@/components/jobs/GenerationProgress";
import RecoveryBanner from "@/components/RecoveryBanner";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  findActiveCardsJob,
  generateCards,
  listCards,
  type CardOut,
} from "@/lib/api/client";
import { notifyCardsSettled } from "@/lib/cards/cardsBus";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { useJobFailure } from "@/lib/hooks/useJobFailureMessage";
import { cancelGenerationJob } from "@/lib/jobs/cancel";
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
  const [actionError, setActionError] = useState<FetchError | null>(null);

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
  const failureInfo = useJobFailure(jobFailed, watchedJobId);

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

  async function handleGenerate() {
    setActionError(null);
    const { data, status, error } = await generateCards(sectionId);
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
    setActionError(describeError(status, "Starting flashcard generation", error));
  }

  if (state.kind === "loading") {
    return (
      <p role="status" className="text-xs text-muted-foreground">
        Loading flashcards…
      </p>
    );
  }

  if (state.kind === "error") {
    return <p className="text-xs text-status-serious">{state.error.message}</p>;
  }

  if (isGenerating) {
    return (
      <GenerationProgress
        job={stalled ? null : job}
        quiet={stalled}
        compact
        onCancel={watchedJobId ? () => cancelGenerationJob(watchedJobId) : undefined}
      />
    );
  }

  if (jobFailed) {
    return (
      <RecoveryBanner
        message={`Generation failed${failureInfo.message ? `: ${failureInfo.message}` : "."}`}
        onRetry={() => void handleGenerate()}
        jobId={watchedJobId}
        errorDetail={failureInfo.detail}
      />
    );
  }

  const hasCards = state.cards.length > 0;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-lg border border-divider bg-surface-raised px-5 py-4">
      <div className="min-w-0 flex-1">
        {/* The count stays its own <span> holding exactly "N flashcard(s)"
            — cards-cta.test.tsx matches that string exactly and, in the
            empty state, asserts no <span> mentions flashcards at all. */}
        <p className="text-sm font-semibold">
          {hasCards ? (
            <span>
              {state.cards.length} flashcard{state.cards.length === 1 ? "" : "s"}
            </span>
          ) : (
            "No flashcards from this section yet"
          )}
        </p>
        <p className="mt-0.5 text-[13px] text-muted-foreground">
          {hasCards
            ? "Generated from this section — they are scheduled in your review queue."
            : "Generate a deck from this section's source text."}
        </p>
      </div>
      {/* No due count: listCards returns no scheduling fields (CardOut has
          no due/interval), so the mock's "Review N due" ships without the
          number rather than with a guessed one. */}
      {hasCards && (
        <Link
          href="/review"
          className="rounded-md bg-accent-700 px-4 py-2 text-[13px] font-medium text-background transition-colors hover:bg-accent-800 active:bg-accent-900"
        >
          Review
        </Link>
      )}
      <button
        type="button"
        onClick={() => void handleGenerate()}
        className="rounded-md border border-border bg-surface-raised px-4 py-2 text-[13px] font-medium transition-colors hover:bg-foreground/[0.07] active:bg-foreground/[0.14]"
      >
        {hasCards ? "Generate more flashcards" : "Generate flashcards"}
      </button>
      {actionError && (
        <div className="w-full">
          <RecoveryBanner
            message={actionError.message}
            onRetry={() => void handleGenerate()}
            errorDetail={actionError.detail}
          />
        </div>
      )}
    </div>
  );
}
