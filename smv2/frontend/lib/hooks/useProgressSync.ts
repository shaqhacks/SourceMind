"use client";

import { useEffect, useRef } from "react";
import type { RefObject } from "react";

import { saveProgress } from "@/lib/api/client";

const SCROLL_SAVE_DEBOUNCE_MS = 1000;

function computeScrollFraction(el: HTMLElement): number {
  const scrollable = el.scrollHeight - el.clientHeight;
  if (scrollable <= 0) return 0;
  return Math.min(1, Math.max(0, el.scrollTop / scrollable));
}

/**
 * Persists reading position: immediately (scroll_pos 0) whenever the
 * active section changes, and debounced (~1s) while scrolling within a
 * section. scroll_pos is a 0..1 fraction of the reading column's
 * scrollable height rather than a raw pixel offset, so resuming works the
 * same regardless of viewport size, font size, or zoom.
 *
 * The very first render is deliberately exempt from the section-change
 * save: that's the resumed section, and immediately re-saving it with
 * scroll_pos 0 would stomp the saved position we just restored, before
 * the resume-scroll effect elsewhere even gets to apply it.
 */
export function useProgressSync(
  courseId: string,
  sectionId: string | null,
  columnRef: RefObject<HTMLElement | null>,
): void {
  const sectionIdRef = useRef(sectionId);
  useEffect(() => {
    sectionIdRef.current = sectionId;
  }, [sectionId]);
  const isInitialMount = useRef(true);

  useEffect(() => {
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }
    if (!sectionId) return;
    saveProgress(courseId, { section_id: sectionId, scroll_pos: 0 });
  }, [courseId, sectionId]);

  useEffect(() => {
    const el = columnRef.current;
    if (!el) return undefined;

    let timer: ReturnType<typeof setTimeout> | null = null;

    function handleScroll() {
      if (timer !== null) clearTimeout(timer);
      timer = setTimeout(() => {
        const currentSectionId = sectionIdRef.current;
        if (!currentSectionId || !el) return;
        saveProgress(courseId, {
          section_id: currentSectionId,
          scroll_pos: computeScrollFraction(el),
        });
      }, SCROLL_SAVE_DEBOUNCE_MS);
    }

    el.addEventListener("scroll", handleScroll);
    return () => {
      el.removeEventListener("scroll", handleScroll);
      if (timer !== null) clearTimeout(timer);
    };
  }, [courseId, columnRef]);
}
