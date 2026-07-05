"use client";

import { useEffect, useRef } from "react";

import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";

export interface ShortcutHint {
  keys: string;
  description: string;
}

export interface ShortcutsOverlayProps {
  open: boolean;
  onClose: () => void;
  shortcuts: ShortcutHint[];
}

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export default function ShortcutsOverlay({ open, onClose, shortcuts }: ShortcutsOverlayProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  // Registered even when closed; the hook itself no-ops while `enabled`
  // (i.e. `open`) is false. Being on top of the scope stack while open is
  // what stops the reader shell's own shortcuts from firing underneath.
  useKeyboardShortcuts({ escape: onClose }, open);

  useEffect(() => {
    if (!open) return undefined;

    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const dialog = dialogRef.current;
    const focusables = dialog
      ? Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
      : [];
    (focusables[0] ?? dialog)?.focus();

    function handleTab(event: KeyboardEvent) {
      if (event.key !== "Tab" || !dialog) return;
      const nodes = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (nodes.length === 0) {
        event.preventDefault();
        return;
      }
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleTab);
    return () => {
      document.removeEventListener("keydown", handleTab);
      previouslyFocused.current?.focus();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Keyboard shortcuts"
        tabIndex={-1}
        className="w-full max-w-md rounded-lg border border-border bg-background p-6 shadow-xl"
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-semibold">Keyboard shortcuts</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md border border-border px-2 py-1 text-sm"
          >
            Esc
          </button>
        </div>
        <ul className="space-y-2 text-sm">
          {shortcuts.map((shortcut) => (
            <li key={shortcut.keys} className="flex items-center justify-between gap-4">
              <span className="text-muted-foreground">{shortcut.description}</span>
              <kbd className="rounded border border-border bg-muted-foreground/10 px-2 py-0.5 font-mono text-xs">
                {shortcut.keys}
              </kbd>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
