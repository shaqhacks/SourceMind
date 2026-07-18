"use client";

import { useMemo, type CSSProperties } from "react";

import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import { useDismissOnOutsideOrEscape } from "@/lib/hooks/useDismissOnOutsideOrEscape";
import type { HighlightColor } from "@/lib/hooks/useHighlights";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";

export interface SelectionPopoverProps {
  /** The live selection's own bounding box (`range.getBoundingClientRect()`
   * — viewport-relative, matching `position: fixed`), captured once by the
   * caller when the selection was made. Not re-measured here: the caller
   * unmounts/remounts this component (new selection = new instance) rather
   * than this component tracking a moving selection itself. */
  anchorRect: DOMRect;
  onColor: (color: HighlightColor) => void;
  onExplain: () => void;
  onClose: () => void;
}

const COLORS: readonly HighlightColor[] = ["yellow", "green", "blue", "pink"];
const GAP_PX = 8;
// Rough popover height used only to decide above-vs-below placement before
// the real element has laid out (this runs on first paint, no measured
// height yet) — doesn't need to be exact, just enough margin that "above"
// isn't picked when it would clip off the top of the viewport.
const ESTIMATED_HEIGHT_PX = 56;

/** Fixed-position placement near the selection: above by default (the
 * conventional floating-toolbar spot), below when there isn't enough room
 * above. `anchorRect` is already viewport-relative (from
 * `getBoundingClientRect()`), which is exactly what `position: fixed`
 * expects — no scroll-offset math needed. */
function popoverStyle(anchorRect: DOMRect): CSSProperties {
  const openAbove = anchorRect.top >= ESTIMATED_HEIGHT_PX + GAP_PX;
  return {
    position: "fixed",
    left: anchorRect.left + anchorRect.width / 2,
    transform: "translateX(-50%)",
    ...(openAbove
      ? { bottom: window.innerHeight - anchorRect.top + GAP_PX }
      : { top: anchorRect.bottom + GAP_PX }),
  };
}

/**
 * Floating toolbar for a live text selection in source-mode reading:
 * four highlight-color swatches plus "Explain" (send the selection to
 * chat). Mounted/unmounted by the caller (ReadingColumn) exactly while a
 * qualifying selection exists — there is no `open` prop, unlike the
 * modal/drawer overlays in this directory, because this component's own
 * lifecycle IS the open/closed state.
 */
export default function SelectionPopover({
  anchorRect,
  onColor,
  onExplain,
  onClose,
}: SelectionPopoverProps) {
  // trap: false — a floating toolbar next to live selected text, not a
  // blocking modal; the reading column behind it stays reachable.
  const dialogRef = useDialogFocus<HTMLDivElement>(true, { trap: false });
  useDismissOnOutsideOrEscape(true, onClose, dialogRef);
  // Own (intentionally empty) scope while mounted: sits on top of the
  // reader shell's arrow/j/k/s/c/o scope so those single-key shortcuts
  // don't fire while the user is mid-annotation, same mechanism as
  // OutlineEditorModal/ShortcutsOverlay.
  useKeyboardShortcuts({}, true);

  const style = useMemo(() => popoverStyle(anchorRect), [anchorRect]);

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-label="Selection actions"
      tabIndex={-1}
      style={style}
      className="z-50 flex items-center gap-1 rounded-lg border border-border bg-background p-1.5 shadow-xl"
    >
      {COLORS.map((color) => (
        <button
          key={color}
          type="button"
          onClick={() => onColor(color)}
          aria-label={`Highlight ${color}`}
          title={`Highlight ${color}`}
          className="h-6 w-6 rounded-full border border-border"
          style={{ backgroundColor: `var(--highlight-${color})` }}
        />
      ))}
      <div aria-hidden="true" className="mx-1 h-5 w-px bg-border" />
      <button
        type="button"
        onClick={onExplain}
        className="whitespace-nowrap rounded-md px-2 py-1 text-sm font-medium hover:bg-muted-foreground/10"
      >
        Explain
      </button>
    </div>
  );
}
