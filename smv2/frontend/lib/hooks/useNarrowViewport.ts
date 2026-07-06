"use client";

import { useSyncExternalStore } from "react";

/**
 * Tracks whether the viewport is narrower than `breakpointPx` via a
 * matchMedia listener — same idiom as useTheme.ts's own
 * prefers-color-scheme tracking (a media query, not a resize listener,
 * so the browser does the debouncing). Used by the reader's chat panel
 * to fall back from a docked three-column layout to an overlay drawer
 * on narrow viewports, where docking would squeeze the reading column
 * uncomfortably narrow.
 */
export function useNarrowViewport(breakpointPx: number): boolean {
  const query = `(max-width: ${breakpointPx}px)`;

  return useSyncExternalStore(
    (onChange) => {
      if (typeof window === "undefined") return () => {};
      const mql = window.matchMedia(query);
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    () => (typeof window === "undefined" ? false : window.matchMedia(query).matches),
    () => false,
  );
}
