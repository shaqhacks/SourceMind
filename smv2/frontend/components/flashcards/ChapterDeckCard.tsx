"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import GenerationProgress from "@/components/jobs/GenerationProgress";
import RecoveryBanner from "@/components/RecoveryBanner";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  findActiveCardsJob,
  generateCards,
  type CardOut,
} from "@/lib/api/client";
import { notifyCardsSettled } from "@/lib/cards/cardsBus";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { useJobFailure } from "@/lib/hooks/useJobFailureMessage";
import { cancelGenerationJob } from "@/lib/jobs/cancel";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

export interface ChapterDeckCardProps {
  courseId: string;
  chapterNumber: number;
  title: string;
  /** This chapter's own content sections (ChapterOut.section_ids) — cards
   * are counted and generated against these only, the same "chapter's own
   * material, not practice/answers" split chapter-scoped test generation
   * already uses (generateTest's chapterLabel excludes answers sections). */
  sectionIds: string[];
  cards: CardOut[];
  dueCount: number;
  isBrowsed: boolean;
  onBrowse: () => void;
}

/**
 * A chapter can have more than one content section (a long chapter split
 * across page-window sections sharing one chapter_label), but useJobEvents
 * only ever watches one job id. Generation therefore runs the section list
 * sequentially — one job at a time — rather than trying to watch several
 * jobs in parallel; the common case is a single section, so this rarely
 * does more than one round trip.
 */
export default function ChapterDeckCard({
  courseId,
  chapterNumber,
  title,
  sectionIds,
  cards,
  dueCount,
  isBrowsed,
  onBrowse,
}: ChapterDeckCardProps) {
  // Sections still to generate after the current job, and "have we started
  // our own generation" — plain refs, not state: neither is ever read
  // during render, only used to sequence effects, so mutating them can't
  // itself need to trigger a re-render. Using useState here instead would
  // mean the queue-advance effect below has to setState synchronously
  // during its own execution (react-hooks/set-state-in-effect's cascading-
  // render anti-pattern); a ref sidesteps that rather than working around it.
  const remainingSectionsRef = useRef<string[]>([]);
  const hasStartedRef = useRef(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [discoveredJobId, setDiscoveredJobId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<FetchError | null>(null);

  const hasCards = cards.length > 0;
  const firstSectionId = sectionIds[0] ?? null;

  // Rediscover a job already in flight for this chapter's first section
  // (from a prior session, or started from the reader) — same idiom as
  // CardsCTA, scoped to the section a fresh "Generate cards" click would
  // start with. Skipped once this instance has generated locally itself.
  useEffect(() => {
    if (hasCards || !firstSectionId || hasStartedRef.current) return undefined;
    let active = true;
    findActiveCardsJob(firstSectionId).then((found) => {
      if (active) setDiscoveredJobId(found?.id ?? null);
    });
    return () => {
      active = false;
    };
  }, [hasCards, firstSectionId]);

  const watchedJobId = activeJobId ?? discoveredJobId;
  const { job, done, stalled } = useJobEvents(watchedJobId);
  const isGenerating = watchedJobId !== null && !done;
  const jobFailed = done && job?.status === "failed";
  // Last job in the chain just succeeded, but the parent hasn't yet
  // refetched and passed fresh `cards` down (it learns via the
  // notifyCardsSettled bus below, one render behind this one) — render a
  // brief "finishing up" status instead of flashing back to the "Generate
  // cards" button in that gap.
  const justFinished = done && watchedJobId !== null && job?.status === "succeeded" && !hasCards;
  const failureInfo = useJobFailure(jobFailed, watchedJobId);

  // Advances the generation queue. Every setState call here happens inside
  // an async continuation (after an await, or in a .then()) rather than
  // synchronously during the effect's own execution — the ref mutations
  // that do run synchronously aren't state, so they don't trigger React's
  // cascading-render warning either.
  useEffect(() => {
    if (!done || !hasStartedRef.current) return;
    if (job?.status !== "succeeded") {
      hasStartedRef.current = false;
      remainingSectionsRef.current = [];
      return;
    }
    const next = remainingSectionsRef.current.shift();
    if (!next) {
      hasStartedRef.current = false;
      notifyReviewSettled();
      for (const id of sectionIds) notifyCardsSettled(id);
      return;
    }
    generateCards(next).then(({ data, status, error }) => {
      if (data) {
        setActiveJobId(data.job_id);
        setDiscoveredJobId(null);
        return;
      }
      if (status === 409) {
        findActiveCardsJob(next).then((found) => setDiscoveredJobId(found?.id ?? null));
        return;
      }
      setActionError(describeError(status, "Starting flashcard generation", error));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done, job?.status]);

  async function handleGenerate() {
    setActionError(null);
    if (sectionIds.length === 0) return;
    const [first, ...rest] = sectionIds;
    remainingSectionsRef.current = rest;
    hasStartedRef.current = true;
    const { data, status, error } = await generateCards(first);
    if (data) {
      setActiveJobId(data.job_id);
      return;
    }
    if (status === 409) {
      const found = await findActiveCardsJob(first);
      setDiscoveredJobId(found?.id ?? null);
      return;
    }
    setActionError(describeError(status, "Starting flashcard generation", error));
  }

  if (hasCards) {
    return (
      <Card className="flex flex-col gap-2.5 p-5">
        <span className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          Chapter {chapterNumber}
        </span>
        <p className="font-heading text-lg">{title}</p>
        <div className="flex flex-wrap gap-1.5">
          {dueCount > 0 ? (
            <Badge tone="accent">{dueCount} due</Badge>
          ) : (
            <Badge tone="neutral">0 due</Badge>
          )}
          <Badge tone="neutral">
            {cards.length} card{cards.length === 1 ? "" : "s"}
          </Badge>
        </div>
        <div className="mt-1 flex items-center gap-2">
          {/* Button.tsx only renders a <button>; a real navigation needs a
           * styled Link instead (no asChild support, and <a> can't nest
           * inside <button>) — classes mirror Button's primary/sm variant. */}
          <Link
            href={`/review?course=${courseId}&start=due`}
            className="rounded-md bg-accent-700 px-2 py-1 font-heading text-xs text-background transition-colors hover:bg-accent-800 active:bg-accent-900"
          >
            Review
          </Link>
          <Button
            variant="secondary"
            size="sm"
            onClick={onBrowse}
            aria-pressed={isBrowsed}
          >
            Browse
          </Button>
        </div>
      </Card>
    );
  }

  // Zero cards: dashed "generate" affordance. No cost estimate — client.ts
  // has getLessonEstimate but no equivalent for card generation, so a price
  // would be fabricated; omitted rather than guessed.
  return (
    <div className="flex flex-col gap-2.5 rounded-lg border border-dashed border-border bg-transparent p-5">
      <span className="text-xs font-semibold tracking-wide text-neutral-600 uppercase">
        Chapter {chapterNumber}
      </span>
      <p className="font-heading text-lg">{title}</p>
      {sectionIds.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          This chapter has no content section to generate cards from.
        </p>
      ) : isGenerating ? (
        <GenerationProgress
          job={stalled ? null : job}
          quiet={stalled}
          compact
          onCancel={watchedJobId ? () => cancelGenerationJob(watchedJobId) : undefined}
        />
      ) : justFinished ? (
        <p role="status" className="text-sm text-muted-foreground">
          Finishing up…
        </p>
      ) : jobFailed ? (
        <RecoveryBanner
          message={`Generation failed${failureInfo.message ? `: ${failureInfo.message}` : "."}`}
          onRetry={() => void handleGenerate()}
          jobId={watchedJobId}
          errorDetail={failureInfo.detail}
        />
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            No cards yet — generate a set from this chapter&apos;s key ideas.
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void handleGenerate()}
            className="self-start"
          >
            Generate cards
          </Button>
        </>
      )}
      {actionError && (
        <RecoveryBanner
          message={actionError.message}
          onRetry={() => void handleGenerate()}
          errorDetail={actionError.detail}
        />
      )}
    </div>
  );
}
