"use client";

import { useCallback, useSyncExternalStore } from "react";

import type { ViewMode } from "@/lib/reader/types";

/**
 * Persists the reader's view mode (source/pages/lesson) per course — a
 * user reading two different books plausibly wants different views for
 * each. Same useSyncExternalStore-backed-preference convention as
 * useTypographyPrefs.ts/useTheme.ts — a plain string value needs none of
 * that hook's raw-string-vs-parsed-object caching dance (primitives
 * compare by value already), so this is simpler.
 */
const VALID_MODES = new Set<string>(["source", "pages", "lesson"]);
const DEFAULT_MODE: ViewMode = "source";

function storageKey(courseId: string): string {
  return `smv2.readerView.${courseId}`;
}

function isViewMode(value: string | null): value is ViewMode {
  return value !== null && VALID_MODES.has(value);
}

function readStoredMode(courseId: string): ViewMode {
  if (typeof window === "undefined") return DEFAULT_MODE;
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(storageKey(courseId));
  } catch {
    raw = null;
  }
  return isViewMode(raw) ? raw : DEFAULT_MODE;
}

function getServerSnapshot(): ViewMode {
  return DEFAULT_MODE;
}

// Module-level pub/sub, same idiom as useTheme.ts/reviewBus.ts: any
// instance persisting a new mode notifies every mounted instance, which
// then re-reads (scoped to its own courseId) on the resulting re-render.
const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

function notify(): void {
  for (const listener of listeners) listener();
}

function persist(courseId: string, mode: ViewMode): void {
  try {
    window.localStorage.setItem(storageKey(courseId), mode);
  } catch {
    // Best-effort — a full or blocked localStorage shouldn't crash the reader.
  }
  notify();
}

export interface UseReaderViewResult {
  /** The last view mode persisted for this course, or "source" if none yet. */
  storedMode: ViewMode;
  setStoredMode: (mode: ViewMode) => void;
}

export function useReaderView(courseId: string): UseReaderViewResult {
  const storedMode = useSyncExternalStore(
    subscribe,
    () => readStoredMode(courseId),
    getServerSnapshot,
  );
  const setStoredMode = useCallback((mode: ViewMode) => persist(courseId, mode), [courseId]);
  return { storedMode, setStoredMode };
}
