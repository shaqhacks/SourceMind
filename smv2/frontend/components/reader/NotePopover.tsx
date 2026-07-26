"use client";

import { useMemo, useState, type CSSProperties } from "react";

import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import { useDismissOnOutsideOrEscape } from "@/lib/hooks/useDismissOnOutsideOrEscape";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";

export interface NotePopoverProps {
  /** Prefilled text for an existing note; empty ("") when composing a new
   * one. `onDelete` present ⇒ edit mode; absent ⇒ composer. */
  initialNote?: string;
  anchorRect: DOMRect;
  onSave: (noteMd: string) => void;
  onDelete?: () => void;
  onClose: () => void;
}

const GAP_PX = 8;
// Rough height used only to decide above-vs-below placement before layout —
// same fixed-position idiom as HighlightEditPopover.popoverStyle.
const ESTIMATED_HEIGHT_PX = 150;

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
 * Floating editor for a positional margin note — one component for both
 * composing a new note (no `onDelete`, "Cancel") and editing an existing one
 * (prefilled, "Delete"). Mirrors HighlightEditPopover's a11y (dismiss on
 * outside/Escape, focus-on-open, its own empty keyboard-shortcut scope so the
 * reader shell's single-key shortcuts ignore the textarea). Save is disabled
 * for an empty/whitespace-only note — note_md is required server-side.
 */
export default function NotePopover({
  initialNote = "",
  anchorRect,
  onSave,
  onDelete,
  onClose,
}: NotePopoverProps) {
  const dialogRef = useDialogFocus<HTMLDivElement>(true, { trap: false });
  useDismissOnOutsideOrEscape(true, onClose, dialogRef);
  useKeyboardShortcuts({}, true);

  const [note, setNote] = useState(initialNote);
  const style = useMemo(() => popoverStyle(anchorRect), [anchorRect]);
  const canSave = note.trim().length > 0;

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-label={onDelete ? "Edit note" : "Add note"}
      tabIndex={-1}
      style={style}
      className="z-50 flex w-64 flex-col gap-2 rounded-lg border border-divider bg-surface-raised p-3 shadow-md"
    >
      <textarea
        value={note}
        onChange={(event) => setNote(event.target.value)}
        placeholder="Write a note…"
        aria-label="Note"
        rows={3}
        className="w-full resize-none rounded-md border border-border bg-background p-2 text-sm outline-none"
      />
      <div className="flex items-center justify-between gap-1 border-t border-divider pt-2">
        {onDelete ? (
          <button
            type="button"
            onClick={onDelete}
            className="rounded-md px-2 py-1 text-sm font-medium text-status-serious transition-colors hover:bg-status-serious-soft"
          >
            Delete
          </button>
        ) : (
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-2 py-1 text-sm font-medium text-muted-foreground transition-colors hover:bg-foreground/[0.07]"
          >
            Cancel
          </button>
        )}
        <button
          type="button"
          onClick={() => {
            if (canSave) onSave(note);
          }}
          disabled={!canSave}
          className="whitespace-nowrap rounded-md bg-accent px-2 py-1 text-sm font-medium text-background transition-colors hover:bg-accent-600 disabled:cursor-not-allowed disabled:opacity-45"
        >
          Save
        </button>
      </div>
    </div>
  );
}
