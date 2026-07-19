/**
 * Shared CSS Custom Highlight API
 * (https://developer.mozilla.org/docs/Web/API/CSS_Custom_Highlight_API)
 * registry plumbing used by every highlight painter in the reader:
 * `useHighlightPainter` (source mode, one container) and
 * `usePdfHighlightPainter` (pages mode, N text-layer containers aggregated
 * into the same document-global registry). `CSS.highlights` is a single
 * registry keyed by name, not scoped to any one painter or container, so
 * the color list, the `hl-<color>` name mapping, the support check, and the
 * "clear everything" cleanup all have to agree across both painters — this
 * module is the one place that owns them.
 */

import type { HighlightColor } from "@/lib/hooks/useHighlights";

export const HIGHLIGHT_COLORS: readonly HighlightColor[] = ["yellow", "green", "blue", "pink"];

export function highlightRegistryName(color: HighlightColor): string {
  return `hl-${color}`;
}

/**
 * Feature-test for the CSS Custom Highlight API. `typeof CSS`/`typeof
 * Highlight` guard the SSR/build-time module graph (no `CSS`/`Highlight`
 * global exists in Node) as well as real unsupported browsers (older
 * Safari/Firefox).
 *
 * Exported as the single source of truth: every painter's own paint gate
 * AND ReadingColumn's selection->popover trigger must agree on this check.
 * Without that, a browser lacking the API could still open a popover,
 * create a highlight row, and have painting silently no-op — the row would
 * exist and be listed elsewhere (NotesPanel), but the selection the user
 * just made would simply vanish with nothing shown for it.
 */
export function isHighlightApiSupported(): boolean {
  return typeof CSS !== "undefined" && !!CSS.highlights && typeof Highlight !== "undefined";
}

// Computed once at module load, not per effect run: browser support for the
// CSS Custom Highlight API doesn't change during a session. Both painters
// import this cached value rather than re-running the check themselves.
export const HIGHLIGHT_API_SUPPORTED = isHighlightApiSupported();

/**
 * Deletes all four color registry names. `CSS.highlights` is a single
 * document-global registry, not scoped to any one painter instance or
 * container — an entry left behind from a previous render (a stale
 * section's ranges, a stale set of PDF pages, or the disabled/unsupported
 * state) would otherwise keep painting on whatever text now occupies the
 * same names. Safe to call even when the API is unsupported.
 */
export function clearHighlightRegistry(): void {
  if (!HIGHLIGHT_API_SUPPORTED) return;
  for (const color of HIGHLIGHT_COLORS) {
    CSS.highlights.delete(highlightRegistryName(color));
  }
}
