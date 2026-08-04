"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";

import {
  THEME_STORAGE_KEY,
  type EffectiveTheme,
  type ThemePreference,
} from "@/lib/theme/bootstrap";

export { THEME_STORAGE_KEY } from "@/lib/theme/bootstrap";
export type { EffectiveTheme, ThemePreference } from "@/lib/theme/bootstrap";

const DARK_MEDIA_QUERY = "(prefers-color-scheme: dark)";

function isThemePreference(value: string | null): value is ThemePreference {
  return value === "system" || value === "light" || value === "dark";
}

function readStoredPreference(): ThemePreference {
  if (typeof window === "undefined") return "system";
  const raw = window.localStorage.getItem(THEME_STORAGE_KEY);
  return isThemePreference(raw) ? raw : "system";
}

function subscribeToSystemScheme(onChange: () => void): () => void {
  const mql = window.matchMedia(DARK_MEDIA_QUERY);
  mql.addEventListener("change", onChange);
  return () => mql.removeEventListener("change", onChange);
}

function getSystemSchemeSnapshot(): EffectiveTheme {
  return window.matchMedia(DARK_MEDIA_QUERY).matches ? "dark" : "light";
}

function getSystemSchemeServerSnapshot(): EffectiveTheme {
  // No accurate answer is possible on the server; the inline no-FOUC script
  // in app/layout.tsx corrects the DOM attribute before paint on the
  // client regardless, and this hook's own components are client-only
  // rendered (see components/reader/CourseReaderClient.tsx), so this
  // default is never actually shown to a user.
  return "light";
}

/**
 * Applying the theme is a DOM mutation on an element React doesn't own the
 * attribute of (see the inline script in app/layout.tsx) — an external
 * system, exactly what an effect is for. It is not a React state update,
 * so it doesn't fall under "don't setState synchronously in an effect".
 */
function applyThemeAttribute(effective: EffectiveTheme): void {
  document.documentElement.dataset.theme = effective;
}

export interface UseThemeResult {
  preference: ThemePreference;
  effective: EffectiveTheme;
  setPreference: (preference: ThemePreference) => void;
}

/**
 * Three-state theme preference (system/light/dark), persisted to
 * localStorage. `effective` is derived, not stored: it's computed from
 * `preference` plus the live OS color-scheme (tracked via
 * useSyncExternalStore, so a change to prefers-color-scheme while
 * "system" is selected re-renders without an effect-driven setState).
 */
export function useTheme(): UseThemeResult {
  const systemScheme = useSyncExternalStore(
    subscribeToSystemScheme,
    getSystemSchemeSnapshot,
    getSystemSchemeServerSnapshot,
  );

  // Preference itself has no external system to subscribe to (it's only
  // ever changed by this hook's own setPreference), so plain useState is
  // the right tool here — useSyncExternalStore is for the OS-level signal.
  const preference = useSyncExternalStore(
    subscribePreference,
    readStoredPreference,
    () => "system" as ThemePreference,
  );

  const effective: EffectiveTheme = preference === "system" ? systemScheme : preference;

  useEffect(() => {
    applyThemeAttribute(effective);
  }, [effective]);

  const setPreference = useCallback((next: ThemePreference) => {
    window.localStorage.setItem(THEME_STORAGE_KEY, next);
    notifyPreferenceChange();
  }, []);

  return { preference, effective, setPreference };
}

// A tiny module-level pub/sub so every useTheme() instance in the tree
// stays in sync when one of them calls setPreference, without resorting
// to a setState-in-effect pattern to "reset" state on an external change.
const preferenceListeners = new Set<() => void>();

function subscribePreference(onChange: () => void): () => void {
  preferenceListeners.add(onChange);
  return () => preferenceListeners.delete(onChange);
}

function notifyPreferenceChange(): void {
  for (const listener of preferenceListeners) listener();
}
