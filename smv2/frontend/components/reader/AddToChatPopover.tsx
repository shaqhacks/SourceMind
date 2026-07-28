"use client";

import { useMemo } from "react";

import { popoverStyle } from "@/lib/annotations/popoverPlacement";
import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import { useDismissOnOutsideOrEscape } from "@/lib/hooks/useDismissOnOutsideOrEscape";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";

export interface AddToChatPopoverProps {
  /** The live selection's own bounding box
   * (`range.getBoundingClientRect()` — viewport-relative, matching
   * `position: fixed`), captured once by the caller when the selection
   * was made. Not re-measured here: the caller unmounts/remounts this
   * component (new selection = new instance) rather than this component
   * tracking a moving selection itself — same convention as
   * SelectionPopover. */
  anchorRect: DOMRect;
  onAdd: () => void;
  onClose: () => void;
}

// Rough popover height used only to decide above-vs-below placement before
// the real element has laid out — see SelectionPopover's identical
// constant for why an estimate (not a measurement) is fine here.
const ESTIMATED_HEIGHT_PX = 40;

/**
 * Floating "Add to chat" toolbar for a live text selection in Pages-mode
 * reading (the original PDF/HTML page rendering). This is plain text
 * selection for chat context — independent of the CSS Custom Highlight
 * API and of persistence, so unlike SelectionPopover there is no color
 * picker and no `selectorFromRange` anchoring involved. Mirrors
 * SelectionPopover's structure (fixed placement, dismiss-on-outside/
 * escape, its own keyboard-shortcut scope) with a single action. Mounted/
 * unmounted by the caller (ReadingColumn) exactly while a qualifying
 * pages-mode selection exists — no `open` prop, same as SelectionPopover.
 */
export default function AddToChatPopover({ anchorRect, onAdd, onClose }: AddToChatPopoverProps) {
  // trap: false — a floating toolbar next to live selected text, not a
  // blocking modal; the pages view behind it stays reachable.
  const dialogRef = useDialogFocus<HTMLDivElement>(true, { trap: false });
  useDismissOnOutsideOrEscape(true, onClose, dialogRef);
  // Own (intentionally empty) scope while mounted, same mechanism as
  // SelectionPopover: sits on top of the reader shell's shortcut scope so
  // single-key shortcuts don't fire while this popover is open.
  useKeyboardShortcuts({}, true);

  const style = useMemo(() => popoverStyle(anchorRect, ESTIMATED_HEIGHT_PX), [anchorRect]);

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-label="Add to chat"
      tabIndex={-1}
      style={style}
      className="z-50 flex items-center gap-1 rounded-lg border border-divider bg-surface-raised p-1.5 shadow-md"
    >
      <button
        type="button"
        onClick={onAdd}
        className="whitespace-nowrap rounded-md px-2 py-1 text-sm font-medium text-accent-700 transition-colors hover:bg-accent/10"
      >
        Add to chat
      </button>
    </div>
  );
}
