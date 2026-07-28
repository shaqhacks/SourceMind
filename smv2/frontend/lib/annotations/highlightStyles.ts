// Injects the ::highlight(hl-*) paint rules at runtime instead of via
// globals.css, because Turbopack/Lightning-CSS (build-time) doesn't
// recognize the ::highlight() pseudo-element and its warning poisons the
// .next cache. Browsers DO support it, so runtime injection is safe.

import { HIGHLIGHT_COLORS, highlightRegistryName } from "./highlightRegistry";

let injected = false;
const STYLE_ID = "smv2-highlight-rules";

export function ensureHighlightStyles(): void {
  if (injected || typeof document === "undefined") return;
  if (document.getElementById(STYLE_ID)) {
    injected = true;
    return;
  }
  const style = document.createElement("style");
  style.id = STYLE_ID;
  // Generated from the single HIGHLIGHT_COLORS source of truth (same
  // registry the painters and popovers use) instead of four hand-written
  // rules that could drift out of sync with it.
  style.textContent = HIGHLIGHT_COLORS.map(
    (color) => `::highlight(${highlightRegistryName(color)}){background-color:var(--highlight-${color});}`,
  ).join("");
  document.head.appendChild(style);
  injected = true;
}
