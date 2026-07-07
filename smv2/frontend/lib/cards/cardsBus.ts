/**
 * Module-level pub/sub, scoped per section, so SectionCards (the full
 * front/back list) learns "a generation job for this section just
 * settled" from CardsCTA (which owns the job-watching) without either
 * component reaching into the other's state — same idiom as
 * lib/review/reviewBus.ts's notifyReviewSettled/subscribeReviewSettled,
 * scoped to a sectionId since this is specifically about "this section's
 * card list may have changed", not a global signal.
 */

type Listener = (sectionId: string) => void;

const listeners = new Set<Listener>();

export function notifyCardsSettled(sectionId: string): void {
  for (const listener of listeners) listener(sectionId);
}

export function subscribeCardsSettled(onSettled: Listener): () => void {
  listeners.add(onSettled);
  return () => listeners.delete(onSettled);
}
