"use client";

import { useCallback, useSyncExternalStore } from "react";

/**
 * Persists the reader sidebar's collapsed/expanded state — a general UI
 * preference (unlike view mode, which is genuinely per-book), so this is
 * global rather than keyed per course. Same useSyncExternalStore-backed-
 * preference convention as useTypographyPrefs.ts/useTheme.ts; a plain
 * boolean needs none of useTypographyPrefs' raw-string-vs-parsed-object
 * caching dance (primitives compare by value already).
 */
const STORAGE_KEY = "smv2.sidebarCollapsed";

function readStored(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "true";
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

function persist(collapsed: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, String(collapsed));
  } catch {
    // Best-effort — a full or blocked localStorage shouldn't crash the reader.
  }
  notify();
}

export interface UseSidebarCollapsedResult {
  collapsed: boolean;
  setCollapsed: (collapsed: boolean) => void;
  toggle: () => void;
}

export function useSidebarCollapsed(): UseSidebarCollapsedResult {
  const collapsed = useSyncExternalStore(subscribe, readStored, getServerSnapshot);
  const setCollapsed = useCallback((value: boolean) => persist(value), []);
  const toggle = useCallback(() => persist(!readStored()), []);
  return { collapsed, setCollapsed, toggle };
}
