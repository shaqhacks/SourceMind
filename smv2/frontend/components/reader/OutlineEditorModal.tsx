"use client";

import { useEffect, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import OutlineConfirmation from "@/components/upload/OutlineConfirmation";
import { describeError, type FetchError } from "@/lib/api/errors";
import { editOutline, listSections, type OutlineOp, type SectionOut } from "@/lib/api/client";
import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import { useDismissOnOutsideOrEscape } from "@/lib/hooks/useDismissOnOutsideOrEscape";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";

export interface OutlineEditorModalProps {
  courseId: string;
  open: boolean;
  onClose: () => void;
  /** Fires with the fresh section list once an edit_outline PATCH applies,
   * so the reader can patch its own section state instead of refetching
   * the whole course. Not called when the user saves with no edits staged. */
  onApplied: (sections: SectionOut[]) => void;
}

/**
 * Reader-side "Edit outline" modal (TopBar button / "o" shortcut): reuses
 * the same OutlineConfirmation editing UI (rename/reorder/delete/merge/split
 * + the review-state-reset warning) the upload flow used to gate first
 * sight of the reader behind, but against the CURRENT course outline
 * (fetched fresh via list_sections on open) and applied through the same
 * edit_outline PATCH — one shared editor, two entry points.
 */
export default function OutlineEditorModal({
  courseId,
  open,
  onClose,
  onApplied,
}: OutlineEditorModalProps) {
  const dialogRef = useDialogFocus<HTMLDivElement>(open);
  // An (intentionally empty) scope still occupies the top of the shared
  // shortcut-scope stack while open — handleGlobalKeyDown only ever
  // consults the topmost scope, so this is what stops the reader shell's
  // own shortcuts (arrows/j/k/s/c/o) from also firing underneath, same
  // mechanism as ShortcutsOverlay.
  useKeyboardShortcuts({}, open);
  // Escape is handled independently of that stack, via useDismissOnOutsideOrEscape's
  // own direct `document` listener: once the outline loads,
  // OutlineConfirmation (a descendant) registers its own scope for "Enter
  // accepts" — mounting later, it ends up ON TOP of any scope registered
  // here and would silently shadow an "escape" handler placed in it.
  useDismissOnOutsideOrEscape(open, onClose, dialogRef);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Edit outline"
        tabIndex={-1}
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg border border-border bg-background p-6 shadow-xl"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">Edit outline</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md border border-border px-2 py-1 text-sm"
          >
            Close
          </button>
        </div>
        <OutlineEditorBody courseId={courseId} onApplied={onApplied} onClose={onClose} />
      </div>
    </div>
  );
}

interface OutlineEditorBodyProps {
  courseId: string;
  onApplied: (sections: SectionOut[]) => void;
  onClose: () => void;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "ready"; sections: SectionOut[] };

/**
 * Split out of OutlineEditorModal so it mounts fresh every time the modal
 * opens (the parent only renders this subtree while `open`) — a plain
 * mount-effect fetch is then all the "reset on reopen" logic needed, no
 * explicit reset-to-loading effect keyed on `open`.
 */
function OutlineEditorBody({ courseId, onApplied, onClose }: OutlineEditorBodyProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listSections(courseId).then(({ data, status }) => {
      if (!active) return;
      if (data) setState({ kind: "ready", sections: data });
      else setState({ kind: "error", error: describeError(status, "Loading outline") });
    });
    return () => {
      active = false;
    };
  }, [courseId]);

  // OutlineConfirmation's own draft state stays mounted (and its staged
  // edits preserved) across a failed apply — the visible "Save changes"
  // button IS the retry, no separate control needed.
  async function handleAccept(operations: OutlineOp[]) {
    if (operations.length === 0) {
      onClose();
      return;
    }
    setApplying(true);
    setApplyError(null);
    const { data } = await editOutline(courseId, operations);
    setApplying(false);
    if (!data) {
      setApplyError("Applying your outline edits failed.");
      return;
    }
    onApplied(data);
    onClose();
  }

  if (state.kind === "loading") {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Loading outline…
      </p>
    );
  }

  if (state.kind === "error") {
    return <ErrorBanner status={state.error.status} message={state.error.message} />;
  }

  return (
    <div className="flex flex-col gap-3">
      {applyError && <ErrorBanner message={applyError} />}
      {applying && (
        <p role="status" className="text-sm text-muted-foreground">
          Saving changes…
        </p>
      )}
      <OutlineConfirmation
        sections={state.sections}
        onAccept={handleAccept}
        heading="Chapters"
        description="Rename, reorder, delete, merge, or split chapters."
        submitLabel="Save changes"
      />
    </div>
  );
}
