"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import Markdown from "@/components/Markdown";
import ReviewGradeControls from "@/components/review/ReviewGradeControls";
import Button from "@/components/ui/Button";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  deleteCard,
  getReviewQueue,
  getReviewSelection,
  listCards,
  patchCard,
  type CardOut,
  type ReviewQueueCardOut,
} from "@/lib/api/client";
import { subscribeCardsSettled } from "@/lib/cards/cardsBus";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

export interface SectionCardsProps {
  courseId: string;
  chapterLabel: string | null;
  sectionId: string;
}

const REVIEW_QUEUE_LIMIT = 200;

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | {
      kind: "loaded";
      cards: CardOut[];
      reviewCardsById: Map<string, ReviewQueueCardOut>;
      reviewError: FetchError | null;
    };

async function fetchCards(
  sectionId: string,
  courseId: string,
  chapterLabel: string | null,
): Promise<LoadState> {
  const cardsPromise = listCards(sectionId);
  const { data, status } = await cardsPromise;
  if (!data) return { kind: "error", error: describeError(status, "Loading flashcards") };
  const reviewResult =
    chapterLabel === null
      ? await getReviewSelection(courseId, data.map((card) => card.id))
      : await getReviewQueue(courseId, { scope: "all", chapterLabel, limit: REVIEW_QUEUE_LIMIT });
  const reviewError =
    !reviewResult.data
      ? describeError(reviewResult.status, "Loading review metadata")
      : null;
  const reviewCardsById = new Map(
    reviewResult.data?.cards.map((card) => [card.id, card] as const) ?? [],
  );
  return { kind: "loaded", cards: data, reviewCardsById, reviewError };
}

/**
 * The full front/back card list for a section, rendered directly below
 * CardsCTA — CardsCTA owns the "N flashcards" count + generate button +
 * empty state, this owns showing/editing/deleting the cards themselves.
 * Renders nothing at zero cards (CardsCTA already covers that).
 */
export default function SectionCards({ courseId, chapterLabel, sectionId }: SectionCardsProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [revealed, setRevealed] = useState<Set<string>>(new Set());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editFront, setEditFront] = useState("");
  const [editBack, setEditBack] = useState("");
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const loadCards = useCallback(() => {
    fetchCards(sectionId, courseId, chapterLabel).then(setState);
  }, [chapterLabel, courseId, sectionId]);

  useEffect(() => {
    let active = true;
    fetchCards(sectionId, courseId, chapterLabel).then((result) => {
      if (active) setState(result);
    });
    return () => {
      active = false;
    };
  }, [chapterLabel, courseId, sectionId]);

  // CardsCTA owns generation's job-watching; this just listens for "a job
  // for this section settled" and refetches — the core ask is cards
  // appearing here immediately after generation, with no navigation.
  useEffect(() => {
    return subscribeCardsSettled((settledSectionId) => {
      if (settledSectionId === sectionId) loadCards();
    });
  }, [sectionId, loadCards]);

  const toggleRevealed = useCallback((cardId: string) => {
    setRevealed((prev) => {
      const next = new Set(prev);
      if (next.has(cardId)) next.delete(cardId);
      else next.add(cardId);
      return next;
    });
  }, []);

  function startEdit(card: CardOut) {
    setEditingId(card.id);
    setEditFront(card.front_md);
    setEditBack(card.back_md);
    setEditError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setEditError(null);
  }

  async function saveEdit(cardId: string) {
    setSaving(true);
    setEditError(null);
    const { data, status } = await patchCard(cardId, { front_md: editFront, back_md: editBack });
    setSaving(false);
    if (data) {
      const savedCard = data;
      setState((prev) => {
        if (prev.kind !== "loaded") return prev;
        const reviewCardsById = new Map(prev.reviewCardsById);
        const reviewCard = reviewCardsById.get(cardId);
        if (reviewCard) {
          reviewCardsById.delete(cardId);
          reviewCardsById.set(savedCard.id, {
            ...reviewCard,
            id: savedCard.id,
            section_id: savedCard.section_id,
            front_md: savedCard.front_md,
            back_md: savedCard.back_md,
          });
        }
        // The edit response carries a NEW, content-addressed id — swap
        // the old entry out entirely rather than patching it in place.
        return {
          ...prev,
          cards: prev.cards.map((c) => (c.id === cardId ? savedCard : c)),
          reviewCardsById,
        };
      });
      setEditingId(null);
      return;
    }
    if (status === 409) {
      setEditError("This duplicates an existing card.");
      return;
    }
    setEditError(describeError(status, "Saving card").message);
  }

  function requestDelete(cardId: string) {
    setConfirmDeleteId(cardId);
    setDeleteError(null);
  }

  async function confirmDelete(cardId: string) {
    setDeletingId(cardId);
    const { ok, status } = await deleteCard(cardId);
    setDeletingId(null);
    if (ok) {
      setState((prev) => {
        if (prev.kind !== "loaded") return prev;
        return { ...prev, cards: prev.cards.filter((c) => c.id !== cardId) };
      });
      setConfirmDeleteId(null);
      // The deleted card's review history goes with it — the due count
      // may have just changed.
      notifyReviewSettled();
      return;
    }
    setDeleteError(describeError(status, "Deleting card").message);
  }

  if (state.kind === "loading" || state.kind === "error" || state.cards.length === 0) {
    return null;
  }

  return (
    <div className="mt-4 flex flex-col gap-3">
      {chapterLabel !== null && (
        <Link
          href={`/review?course=${encodeURIComponent(courseId)}&scope=all&chapter=${encodeURIComponent(
            chapterLabel,
          )}`}
          className="self-start text-xs font-medium text-accent underline"
        >
          Review this chapter
        </Link>
      )}
      {state.reviewError && (
        <div
          role="alert"
          className="rounded-md border border-accent/30 bg-accent-soft px-3 py-2 text-xs text-muted-foreground"
        >
          <p>{state.reviewError.message}</p>
          <button
            type="button"
            onClick={loadCards}
            className="mt-1 font-medium text-accent underline"
          >
            Retry review metadata
          </button>
        </div>
      )}
      {state.cards.map((card) => {
        const isEditing = editingId === card.id;
        const isRevealed = revealed.has(card.id);
        const isConfirmingDelete = confirmDeleteId === card.id;
        const reviewCard = state.reviewCardsById.get(card.id);

        return (
          <div key={card.id} className="rounded-lg border border-divider bg-surface-raised p-3 text-sm">
            {isEditing ? (
              <div className="flex flex-col gap-2">
                <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                  Front
                  <textarea
                    value={editFront}
                    onChange={(event) => setEditFront(event.target.value)}
                    rows={3}
                    className="rounded-md border border-border bg-background p-2 font-mono text-xs"
                  />
                </label>
                <label className="flex flex-col gap-1 text-xs font-medium text-muted-foreground">
                  Back
                  <textarea
                    value={editBack}
                    onChange={(event) => setEditBack(event.target.value)}
                    rows={3}
                    className="rounded-md border border-border bg-background p-2 font-mono text-xs"
                  />
                </label>
                {editError && <p className="text-xs text-status-serious">{editError}</p>}
                <div className="flex gap-2">
                  <Button variant="primary" size="sm" onClick={() => void saveEdit(card.id)} disabled={saving}>
                    {saving ? "Saving…" : "Save"}
                  </Button>
                  <button
                    type="button"
                    onClick={cancelEdit}
                    disabled={saving}
                    className="rounded-md border border-border bg-surface-raised px-3 py-1 text-xs font-medium transition-colors hover:bg-foreground/[0.07] disabled:opacity-50"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <Markdown>{card.front_md}</Markdown>
                  </div>
                  {card.origin === "user" && (
                    <span className="shrink-0 rounded-[6px] bg-neutral-100 px-2 py-0.5 text-[10px] font-medium text-neutral-800">
                      edited
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => toggleRevealed(card.id)}
                  aria-expanded={isRevealed}
                  className="self-start text-xs font-medium text-accent underline"
                >
                  {isRevealed ? "Hide answer" : "Show answer"}
                </button>
                {isRevealed && (
                  <div className="border-t border-divider pt-2">
                    <Markdown>{card.back_md}</Markdown>
                  </div>
                )}
                {isRevealed && !isConfirmingDelete && reviewCard && (
                  <ReviewGradeControls card={reviewCard} className="pt-1" />
                )}

                {deleteError && confirmDeleteId === null && (
                  <p className="text-xs text-status-serious">{deleteError}</p>
                )}

                <div className="mt-1 flex items-center justify-end gap-2 text-xs">
                  {isConfirmingDelete ? (
                    <>
                      <span className="text-muted-foreground">
                        Delete this card? This removes its review history.
                      </span>
                      <button
                        type="button"
                        onClick={() => void confirmDelete(card.id)}
                        disabled={deletingId === card.id}
                        className="font-medium text-status-serious disabled:opacity-50"
                      >
                        {deletingId === card.id ? "Deleting…" : "Confirm"}
                      </button>
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(null)}
                        className="text-muted-foreground"
                      >
                        Cancel
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => startEdit(card)}
                        className="font-medium text-accent"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => requestDelete(card.id)}
                        className="font-medium text-status-serious"
                      >
                        Delete
                      </button>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
