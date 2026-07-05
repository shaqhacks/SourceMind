"use client";

import { useCallback, useEffect, useRef } from "react";

/**
 * usePolling — runs `fn` on a fixed interval while `enabled` is true, clearing
 * automatically on unmount or when `enabled` flips false. `fn` may return (or
 * resolve to) a truthy value to signal "stop polling now" (terminal state
 * reached); a falsy return keeps the interval going. Errors thrown by `fn`
 * are swallowed so a transient network blip doesn't kill the poll.
 *
 * Returns a `stop()` function callers can invoke to cancel polling early from
 * outside the interval (e.g. a manual cancel action).
 *
 * @param {() => any} fn
 * @param {{interval?: number, enabled?: boolean, immediate?: boolean}} [options]
 */
export function usePolling(fn, { interval = 3000, enabled = true, immediate = false } = {}) {
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const timerRef = useRef(null);

  const stop = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;

    let cancelled = false;

    const tick = async () => {
      let done = false;
      try {
        done = await fnRef.current();
      } catch {
        // transient error — keep polling
      }
      if (!cancelled && done) stop();
    };

    if (immediate) tick();
    timerRef.current = setInterval(tick, interval);

    return () => {
      cancelled = true;
      stop();
    };
  }, [enabled, interval, immediate, stop]);

  return stop;
}
