/**
 * Module-level pub/sub so the nav due-badge (rendered once, high up in the
 * tree) can be told "the due count may have changed" by whatever deeply
 * nested component just graded a card or a generation just settled —
 * same idiom as useTheme.ts's preferenceListeners/notifyPreferenceChange,
 * chosen for consistency rather than reaching for a context provider.
 */

const listeners = new Set<() => void>();

export function notifyReviewSettled(): void {
  for (const listener of listeners) listener();
}

export function subscribeReviewSettled(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}
