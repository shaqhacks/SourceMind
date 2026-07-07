"use client";

import { useEffect, useState } from "react";

import { LEARNING_VIDEOS } from "@/lib/dashboard/videos";

const STORAGE_KEY = "smv2.dashboard.videos";

/**
 * Bottom-of-dashboard learning-science explainers (spec §4). Direct
 * iframes by explicit user decision; youtube-nocookie + loading=lazy keep
 * it private-ish and free until scrolled into view. Collapse state
 * persists so it stays out of the way once dismissed.
 */
export default function VideoSection() {
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setCollapsed(localStorage.getItem(STORAGE_KEY) === "collapsed");
  }, []);

  function toggle() {
    setCollapsed((value) => {
      const next = !value;
      localStorage.setItem(STORAGE_KEY, next ? "collapsed" : "expanded");
      return next;
    });
  }

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
