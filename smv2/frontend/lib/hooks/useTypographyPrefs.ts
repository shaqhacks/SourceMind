"use client";

import { useCallback, useSyncExternalStore } from "react";
import type { CSSProperties } from "react";

export interface TypographyPrefs {
  fontSize: number; // px
  measure: number; // ch
  lineHeight: number; // unitless
}

export const TYPOGRAPHY_STORAGE_KEY = "smv2.typography";

export const FONT_SIZE_RANGE = { min: 16, max: 22 } as const;
export const MEASURE_RANGE = { min: 55, max: 90 } as const;
export const LINE_HEIGHT_RANGE = { min: 1.4, max: 1.9 } as const;

const DEFAULT_PREFS: TypographyPrefs = { fontSize: 18, measure: 70, lineHeight: 1.6 };

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function sanitize(raw: Partial<Record<keyof TypographyPrefs, unknown>> | null): TypographyPrefs {
  if (!raw) return DEFAULT_PREFS;
  const fontSize = Number(raw.fontSize);
  const measure = Number(raw.measure);
  const lineHeight = Number(raw.lineHeight);
  return {
    fontSize: clamp(
      Number.isFinite(fontSize) ? fontSize : DEFAULT_PREFS.fontSize,
      FONT_SIZE_RANGE.min,
      FONT_SIZE_RANGE.max,
    ),
    measure: clamp(
      Number.isFinite(measure) ? measure : DEFAULT_PREFS.measure,
      MEASURE_RANGE.min,
      MEASURE_RANGE.max,
    ),
    lineHeight: clamp(
      Number.isFinite(lineHeight) ? lineHeight : DEFAULT_PREFS.lineHeight,
      LINE_HEIGHT_RANGE.min,
      LINE_HEIGHT_RANGE.max,
    ),
  };
}

// useSyncExternalStore requires getSnapshot to return a referentially
// stable value when nothing changed (React compares with Object.is and
// re-renders in a loop otherwise) — cache the parsed object against the
// raw string it came from, rather than reparsing (and reallocating) a
// fresh object on every call.
let cachedRaw: string | null = null;
let cachedPrefs: TypographyPrefs = DEFAULT_PREFS;

function readStoredPrefs(): TypographyPrefs {
  if (typeof window === "undefined") return DEFAULT_PREFS;
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(TYPOGRAPHY_STORAGE_KEY);
  } catch {
    raw = null;
  }
  if (raw === cachedRaw) {
    return cachedPrefs;
  }
  cachedRaw = raw;
  try {
    cachedPrefs = raw ? sanitize(JSON.parse(raw)) : DEFAULT_PREFS;
  } catch {
    cachedPrefs = DEFAULT_PREFS;
  }
  return cachedPrefs;
}

function getServerSnapshot(): TypographyPrefs {
  return DEFAULT_PREFS;
}

// Same module-level pub/sub pattern as useTheme.ts: every hook instance
// (the popover and the reading column both call this hook) stays in sync
// when one of them writes a new value, via useSyncExternalStore rather
// than an effect that resets state.
const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

function notify(): void {
  for (const listener of listeners) listener();
}

function persist(prefs: TypographyPrefs): void {
  window.localStorage.setItem(TYPOGRAPHY_STORAGE_KEY, JSON.stringify(prefs));
  notify();
}

export function prefsToCssVars(prefs: TypographyPrefs): CSSProperties {
  return {
    "--reading-font-size": `${prefs.fontSize}px`,
    "--reading-measure": `${prefs.measure}ch`,
    "--reading-line-height": String(prefs.lineHeight),
  } as CSSProperties;
}

export interface UseTypographyPrefsResult {
  prefs: TypographyPrefs;
  setFontSize: (value: number) => void;
  setMeasure: (value: number) => void;
  setLineHeight: (value: number) => void;
  cssVars: CSSProperties;
}

export function useTypographyPrefs(): UseTypographyPrefsResult {
  const prefs = useSyncExternalStore(subscribe, readStoredPrefs, getServerSnapshot);

  const setFontSize = useCallback((value: number) => {
    persist(sanitize({ ...readStoredPrefs(), fontSize: value }));
  }, []);
  const setMeasure = useCallback((value: number) => {
    persist(sanitize({ ...readStoredPrefs(), measure: value }));
  }, []);
  const setLineHeight = useCallback((value: number) => {
    persist(sanitize({ ...readStoredPrefs(), lineHeight: value }));
  }, []);

  return { prefs, setFontSize, setMeasure, setLineHeight, cssVars: prefsToCssVars(prefs) };
}
