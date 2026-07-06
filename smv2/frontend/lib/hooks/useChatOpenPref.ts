"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * Persists whether the reader's chat panel is open, per course — same
 * useSyncExternalStore-backed-preference convention as useReaderView.ts
 * (view mode) and useSidebarCollapsed.ts (a plain boolean needs none of
 * useTypographyPrefs' raw-string-vs-parsed-object caching dance).
 */
function storageKey(courseId: string): string {
  return `smv2.chatOpen.${courseId}`;
}

function readStored(courseId: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(storageKey(courseId)) === "true";
  } catch {
    return false;
  }
}

function getServerSnapshot(): boolean {
  return false;
}

const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

function notify(): void {
  for (const listener of listeners) listener();
}

function persist(courseId: string, open: boolean): void {
  try {
    window.localStorage.setItem(storageKey(courseId), String(open));
  } catch {
    // Best-effort — a full or blocked localStorage shouldn't crash the reader.
  }
  notify();
}

export interface UseChatOpenPrefResult {
  open: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
}

export function useChatOpenPref(courseId: string): UseChatOpenPrefResult {
  const open = useSyncExternalStore(subscribe, () => readStored(courseId), getServerSnapshot);
  const setOpen = useCallback((value: boolean) => persist(courseId, value), [courseId]);
  const toggle = useCallback(() => persist(courseId, !readStored(courseId)), [courseId]);
  return { open, setOpen, toggle };
}
