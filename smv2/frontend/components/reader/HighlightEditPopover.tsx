"use client";

import { useMemo, useState, type CSSProperties } from "react";

import type { HighlightOut, HighlightUpdateIn } from "@/lib/api/client";
import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import { useDismissOnOutsideOrEscape } from "@/lib/hooks/useDismissOnOutsideOrEscape";
import type { HighlightColor } from "@/lib/hooks/useHighlights";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";

export interface HighlightEditPopoverProps {
  highlight: HighlightOut;
  /** The highlight's own resolved range, viewport-relative (matching
   * `position: fixed`) — same convention as SelectionPopover's
   * `anchorRect`, captured once by the caller (ReadingColumn) when the
   * click that opened this popover was hit-tested. */
  anchorRect: DOMRect;
  onSave: (patch: HighlightUpdateIn) => void;
  onDelete: () => void;
  onExplain: () => void;
  onClose: () => void;
}

const COLORS: readonly HighlightColor[] = ["yellow", "green", "blue", "pink"];
const GAP_PX = 8;
// Rough popover height used only to decide above-vs-below placement before
// the real element has laid out — taller than SelectionPopover's estimate
// since this popover also has a textarea and a button row.
const ESTIMATED_HEIGHT_PX = 170;

/** Same fixed-position placement logic as SelectionPopover.popoverStyle —
 * duplicated rather than shared because the two components' estimated
 * heights differ and there's no third caller yet to justify extracting a
 * shared helper. */
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
 * Floating editor for an EXISTING highlight, opened by clicking painted
 * source text (see ReadingColumn's `highlightAtPoint` hit-test wiring).
 * Mirrors SelectionPopover's structure/a11y (dismiss-on-outside-or-Escape,
 * focus-on-open, its own keyboard-shortcut scope) but edits a row instead
 * of creating one: a note textarea plus Delete, on top of SelectionPopover's
 * recolor swatches and Add to chat.
 *
 * The note field is a real `<textarea>` (not a div/contentEditable) so the
 * reader shell's global single-key shortcuts (arrows, j/k/s/c/o) ignore it
 * via useKeyboardShortcuts' `isEditableTarget` check while the user types —
 * the same reason SelectionPopover's own empty shortcut scope exists, this
 * component doesn't also need per-character guards of its own.
 *
 * Every action (Save, a color swatch, Delete, Explain) only invokes its
 * prop callback — it never calls `onClose` itself. Closing after an action
 * is the caller's decision, same convention as SelectionPopover's
 * onColor/onExplain (ReadingColumn closes the popover in its own
 * onSave/onDelete/onExplain wrappers, after calling updateOne/deleteOne/
 * onExplainSelection).
 */
export default function HighlightEditPopover({
  highlight,
  anchorRect,
  onSave,
  onDelete,
  onExplain,
  onClose,
}: HighlightEditPopoverProps) {
  // trap: false — a floating toolbar next to the highlighted text, not a
  // blocking modal; the reading column behind it stays reachable.
  const dialogRef = useDialogFocus<HTMLDivElement>(true, { trap: false });
  useDismissOnOutsideOrEscape(true, onClose, dialogRef);
  // Own (intentionally empty) scope while mounted — see SelectionPopover's
  // identical use of this hook for why.
  useKeyboardShortcuts({}, true);

  const [note, setNote] = useState(highlight.note_md ?? "");

  const style = useMemo(() => popoverStyle(anchorRect), [anchorRect]);

  // An empty/whitespace-only note is sent as `null`, not `""`: per
  // HighlightUpdateIn's own docstring ("an explicit null note_md clears
  // the note"), null is the real "no note" state the backend already
  // recognizes — clearing the textarea and hitting Save should actually
  // clear a previously-saved note, not leave it holding an empty string
  // that reads the same in the UI but isn't the same value server-side.
  function handleSaveNote() {
    const trimmed = note.trim();
    onSave({ note_md: trimmed.length > 0 ? note : null });
  }

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-label="Highlight actions"
      tabIndex={-1}
      style={style}
      className="z-50 flex w-64 flex-col gap-2 rounded-lg border border-divider bg-surface-raised p-3 shadow-md"
    >
      <textarea
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="Add a note…"
        aria-label="Highlight note"
        rows={3}
        className="w-full resize-none rounded-md border border-border bg-background p-2 text-sm outline-none"
      />
      <div className="flex items-center gap-1">
        {COLORS.map((color) => (
          <button
            key={color}
            type="button"
            onClick={() => onSave({ color })}
            aria-label={`Highlight ${color}`}
            aria-pressed={highlight.color === color}
            title={`Highlight ${color}`}
            className={`h-6 w-6 rounded-full transition-transform hover:scale-110 ${
              highlight.color === color
                ? "border-2 border-accent"
                : "border border-border"
            }`}
            style={{ backgroundColor: `var(--highlight-${color})` }}
          />
        ))}
      </div>
      <div className="flex items-center justify-between gap-1 border-t border-divider pt-2">
        <button
          type="button"
          onClick={onDelete}
          className="rounded-md px-2 py-1 text-sm font-medium text-status-serious transition-colors hover:bg-status-serious-soft"
        >
          Delete
        </button>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={onExplain}
            className="whitespace-nowrap rounded-md px-2 py-1 text-sm font-medium text-accent-700 transition-colors hover:bg-accent/10"
          >
            Add to chat
          </button>
          <button
            type="button"
            onClick={handleSaveNote}
            className="whitespace-nowrap rounded-md bg-accent px-2 py-1 text-sm font-medium text-background transition-colors hover:bg-accent-600"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
