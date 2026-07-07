"use client";

import { useCallback, useSyncExternalStore } from "react";

import { LEARNING_VIDEOS } from "@/lib/dashboard/videos";

const STORAGE_KEY = "smv2.dashboard.videos";

function readCollapsed(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "collapsed";
  } catch {
    return false;
  }
}

function getServerSnapshot(): boolean {
  return false;
}

const listeners = new Set<() => void>();

function subscribe(onChange: () => void): () => void {
  listeners.add(onChange);
  return () => listeners.delete(onChange);
}

function persist(collapsed: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, collapsed ? "collapsed" : "expanded");
  } catch {
    // Best-effort — a full or blocked localStorage shouldn't crash the dashboard.
  }
  for (const listener of listeners) listener();
}

/**
 * Bottom-of-dashboard learning-science explainers (spec §4). Direct
 * iframes by explicit user decision; youtube-nocookie + loading=lazy keep
 * it private-ish and free until scrolled into view. Collapse state
 * persists so it stays out of the way once dismissed — same
 * useSyncExternalStore-backed-preference convention as
 * lib/hooks/useSidebarCollapsed.ts (avoids a hydration-mismatch flash and
 * the react-hooks/set-state-in-effect footgun of setState-on-mount).
 */
export default function VideoSection() {
  const collapsed = useSyncExternalStore(subscribe, readCollapsed, getServerSnapshot);
  const toggle = useCallback(() => persist(!readCollapsed()), []);

  if (LEARNING_VIDEOS.length === 0) return null;

  return (
    <section aria-labelledby="learning-science-heading" className="flex flex-col gap-3">
      <button
        type="button"
        onClick={toggle}
        aria-expanded={!collapsed}
        className="flex items-center gap-2 self-start text-sm font-semibold"
      >
        <span aria-hidden="true">{collapsed ? "▸" : "▾"}</span>
        <span id="learning-science-heading">Learning science — why this app works this way</span>
      </button>
      {!collapsed && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {LEARNING_VIDEOS.map((video) => (
            <figure key={video.videoId} className="flex flex-col gap-2">
              <iframe
                src={`https://www.youtube-nocookie.com/embed/${video.videoId}`}
                title={video.title}
                loading="lazy"
                allowFullScreen
                className="aspect-video w-full rounded-lg border border-border"
              />
              <figcaption className="text-xs text-muted-foreground">{video.blurb}</figcaption>
            </figure>
          ))}
        </div>
      )}
    </section>
  );
}
