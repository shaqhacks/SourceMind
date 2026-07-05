"use client";

import { useCallback, useSyncExternalStore } from "react";

export const SAMPLE_HINT_STORAGE_KEY = "smv2.hints.sample";

function readDismissed(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(SAMPLE_HINT_STORAGE_KEY) === "1";
}

function getServerSnapshot(): boolean {
  // No accurate answer is possible on the server; app/page.tsx is
  // client-only rendered content anyway (see useTheme.ts for the same
  // reasoning), and useSyncExternalStore re-syncs against the real
  // localStorage value right after hydration.
  return false;
}

// Module-level pub/sub — same idiom as useTheme.ts's preferenceListeners,
// so every useSampleHintDismissed() instance stays in sync if dismiss()
// is ever called from more than one place.
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
export function useSampleHintDismissed(): UseSampleHintResult {
  const dismissed = useSyncExternalStore(subscribe, readDismissed, getServerSnapshot);

  const dismiss = useCallback(() => {
    window.localStorage.setItem(SAMPLE_HINT_STORAGE_KEY, "1");
    notify();
  }, []);

  return { dismissed, dismiss };
}
