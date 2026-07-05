"use client";

import { useEffect, useRef } from "react";
import type { RefObject } from "react";
import { usePathname } from "next/navigation";

// Module-level (not per-component): persists across mount/unmount of
// whichever page component currently owns the route, only resetting on an
// actual browser reload. Lets every page's useRouteFocus call agree on
// whether the app's very first paint has already happened.
let hasMountedOnce = false;

/**
 * Moves focus to `ref`'s element whenever the route changes to a new
 * pathname — but not on the app's initial hard load, where the browser's
 * own default focus placement is correct and grabbing focus away from it
 * would be surprising for a screen-reader user landing fresh.
 *
 * Pass `ready=false` while the target isn't in the DOM yet (e.g. a page
 * still loading its data); the hook has no dependency array, so it keeps
 * re-checking every render until `ready` and `ref.current` line up.
 */
export function useRouteFocus(ref: RefObject<HTMLElement | null>, ready = true): void {
  const pathname = usePathname();
  const handledForPathname = useRef<string | null>(null);

  useEffect(() => {
    if (!ready) return;
    if (handledForPathname.current === pathname) return;
    handledForPathname.current = pathname;

    const isInitialLoad = !hasMountedOnce;
    hasMountedOnce = true;
    if (isInitialLoad) return;

    ref.current?.focus();
  });
}
