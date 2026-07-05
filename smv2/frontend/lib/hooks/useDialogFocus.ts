"use client";

import { useEffect, useRef } from "react";
import type { RefObject } from "react";

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

export interface UseDialogFocusOptions {
  /** Trap Tab/Shift+Tab within the container while open — for true modal
   * dialogs. Non-modal drawers/popovers should pass `false`. Default true. */
  trap?: boolean;
}

/**
 * Shared open/close focus management for dialogs, drawers, and popovers:
 * on open, remembers whatever had focus and moves focus into the
 * container (its first focusable element, or the container itself); on
 * close, restores focus to what had it before. Extracted from
 * ShortcutsOverlay's original inline implementation so every overlay in
 * the app gets the same behavior instead of reimplementing it slightly
 * differently each time.
 */
export function useDialogFocus<T extends HTMLElement>(
  open: boolean,
  options: UseDialogFocusOptions = {},
): RefObject<T | null> {
  const containerRef = useRef<T>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);
  const trap = options.trap ?? true;

  useEffect(() => {
    if (!open) return undefined;

    previouslyFocused.current = document.activeElement as HTMLElement | null;
    const container = containerRef.current;
    const focusables = container
      ? Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
      : [];
    (focusables[0] ?? container)?.focus();

    if (!trap) {
      return () => {
        previouslyFocused.current?.focus();
      };
    }

    function handleTab(event: KeyboardEvent) {
      if (event.key !== "Tab" || !container) return;
      const nodes = Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
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
  }, [open, trap]);

  return containerRef;
}
