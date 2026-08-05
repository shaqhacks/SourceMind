"use client";

import { useCallback, useSyncExternalStore } from "react";

export const SAMPLE_HINT_STORAGE_KEY = "smv2.hints.sample";

function storageKey(courseId: string): string {
  return `${SAMPLE_HINT_STORAGE_KEY}.${courseId}`;
}

function readDismissed(courseId: string): boolean {
  if (typeof window === "undefined") return false;
  // Deliberately do not treat the legacy global key as dismissed here:
  // that old shape suppressed every sample course after one dismissal.
  return window.localStorage.getItem(storageKey(courseId)) === "1";
}

function getServerSnapshot(): boolean {
  // No accurate answer is possible on the server; app/page.tsx is
  // client-only rendered content anyway (see useTheme.ts for the same
  // reasoning), and useSyncExternalStore re-syncs against the real
  // localStorage value right after hydration.
  return false;
}

// Module-level pub/sub — same idiom as useTheme.ts's preferenceListeners,
// so every useSampleHintDismissed(courseId) instance stays in sync if
// dismiss() is ever called from more than one place.
const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

function notify(): void {
  for (const listener of listeners) listener();
}

export interface UseSampleHintResult {
  dismissed: boolean;
  dismiss: () => void;
}

/** One-time, permanently-dismissible "this is the sample course" hint. */
export function useSampleHintDismissed(courseId: string): UseSampleHintResult {
  const dismissed = useSyncExternalStore(
    subscribe,
    () => readDismissed(courseId),
    getServerSnapshot,
  );

  const dismiss = useCallback(() => {
    window.localStorage.setItem(storageKey(courseId), "1");
    notify();
  }, [courseId]);

  return { dismissed, dismiss };
}
