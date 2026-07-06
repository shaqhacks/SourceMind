import type { ViewMode } from "./types";

/**
 * The "s" shortcut's cycle order: source -> pages -> lesson -> source.
 * "pages" is skipped entirely when unavailable for the active section (no
 * asset_id) — a disabled option shouldn't still occupy a slot in the
 * cycle, or "s" would land on it and show nothing useful.
 */
export function nextViewMode(current: ViewMode, pagesAvailable: boolean): ViewMode {
  const order: ViewMode[] = pagesAvailable ? ["source", "pages", "lesson"] : ["source", "lesson"];
  const index = order.indexOf(current);
  return order[(index + 1) % order.length];
}
