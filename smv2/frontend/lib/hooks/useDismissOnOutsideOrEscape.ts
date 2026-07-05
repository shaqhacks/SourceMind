"use client";

import { useEffect } from "react";
import type { RefObject } from "react";

/**
 * Closes a non-modal popover on Escape or a pointerdown outside
 * `containerRef`'s element — the pattern TypographyControls already used
 * inline, extracted so QuizzesPanel (and any future popover) gets the
 * same dismissal behavior instead of missing it.
 */
export function useDismissOnOutsideOrEscape(
  open: boolean,
  onClose: () => void,
  containerRef: RefObject<HTMLElement | null>,
): void {
  useEffect(() => {
    if (!open) return undefined;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    function handlePointerDown(event: PointerEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        onClose();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [open, onClose, containerRef]);
}
