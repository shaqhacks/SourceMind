"use client";

import { useEffect, useState } from "react";
import type { RefObject } from "react";

/**
 * Lazy-mount trigger shared by PdfPagesView/HtmlPagesView: a page only
 * renders its real content once IntersectionObserver reports it's about
 * to scroll into view (rootMargin gives it a head start) — a 40-page
 * section must not render/mount every page up front. Default root (the
 * browser viewport) is correct even though a page is nested inside a
 * scrolling overflow-y-auto column — IntersectionObserver measures
 * against each target's actual clipped screen rect, which already
 * reflects ancestor scroll/overflow, so no explicit `root` is needed.
 * Disconnects after the first hit: once a page has mounted it stays
 * mounted, there's no un-mounting as it scrolls back out.
 */
export function useNearViewport(containerRef: RefObject<Element | null>): boolean {
  // No IntersectionObserver support: fail open (treat as always visible)
  // rather than never rendering — computed as the lazy initial state
  // itself (support doesn't change mid-session) rather than a synchronous
  // setState in the effect below, which react-hooks/set-state-in-effect
  // flags as an avoidable cascading render.
  const [nearViewport, setNearViewport] = useState(
    () => typeof IntersectionObserver === "undefined",
  );

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return undefined;
    const el = containerRef.current;
    if (!el) return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setNearViewport(true);
          observer.disconnect();
        }
      },
      { rootMargin: "200px 0px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [containerRef]);

  return nearViewport;
}
