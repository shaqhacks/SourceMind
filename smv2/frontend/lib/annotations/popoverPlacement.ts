import type { CSSProperties } from "react";

const GAP_PX = 8;

/**
 * Fixed-position placement near a selection/highlight/note anchor: above by
 * default (the conventional floating-toolbar spot), below when there isn't
 * enough room above. `anchorRect` is already viewport-relative (from
 * `getBoundingClientRect()`), which is exactly what `position: fixed`
 * expects — no scroll-offset math needed.
 *
 * `estimatedHeightPx` is a rough popover height used only to decide
 * above-vs-below placement before the real element has laid out (this runs
 * on first paint, no measured height yet) — doesn't need to be exact, just
 * enough margin that "above" isn't picked when it would clip off the top of
 * the viewport. Each caller passes its own estimate (SelectionPopover: 56,
 * HighlightEditPopover: 170, AddToChatPopover: 40, NotePopover: 150) since
 * their popovers' real heights differ.
 *
 * Shared by SelectionPopover, HighlightEditPopover, AddToChatPopover, and
 * NotePopover — the four floating reader popovers all used this exact
 * placement logic as separate copies before this extraction.
 */
export function popoverStyle(anchorRect: DOMRect, estimatedHeightPx: number): CSSProperties {
  const openAbove = anchorRect.top >= estimatedHeightPx + GAP_PX;
  return {
    position: "fixed",
    left: anchorRect.left + anchorRect.width / 2,
    transform: "translateX(-50%)",
    ...(openAbove
      ? { bottom: window.innerHeight - anchorRect.top + GAP_PX }
      : { top: anchorRect.bottom + GAP_PX }),
  };
}
