"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { library } from "../lib/api";
import { usePolling } from "../lib/usePolling";

const SEEN_KEY = "sourcemind:seen_ready";
const POLL_MS = 10000;

function loadSeen() {
  try {
    const raw = localStorage.getItem(SEEN_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function saveSeen(ids) {
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify(ids));
  } catch {
    // localStorage may be unavailable (private mode) — best-effort only.
  }
}

function BellIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 2a6 6 0 0 0-6 6c0 3.5-1 5-2 6h16c-1-1-2-2.5-2-6a6 6 0 0 0-6-6Z"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinejoin="round"
      />
      <path d="M9.5 19a2.5 2.5 0 0 0 5 0" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

export default function Notifications() {
  const [data, setData] = useState({ due_review_count: 0, courses: [] });
  const [open, setOpen] = useState(false);
  const [seen, setSeen] = useState([]); // acknowledged ready course ids (localStorage)
  const prevReadyRef = useRef(null); // ready ids from the previous poll (session baseline)
  const firedRef = useRef(new Set()); // course ids we've already browser-notified

  // Load acknowledged set from localStorage on mount.
  useEffect(() => {
    setSeen(loadSeen());
  }, []);

  // Request browser-notification permission once, best-effort.
  useEffect(() => {
    try {
      if (typeof window !== "undefined" && "Notification" in window && Notification.permission === "default") {
        const p = Notification.requestPermission();
        if (p && typeof p.catch === "function") p.catch(() => {});
      }
    } catch {
      // never block the UI on permission issues
    }
  }, []);

  // Poll the backend on mount and every POLL_MS.
  const cancelledRef = useRef(false);
  useEffect(() => {
    cancelledRef.current = false;
    return () => {
      cancelledRef.current = true;
    };
  }, []);

  const poll = useCallback(async () => {
    let res;
    try {
      res = await library.notifications();
    } catch {
      return; // API unavailable — keep last known state, never throw
    }
    if (cancelledRef.current || !res) return;

    const courses = Array.isArray(res.courses) ? res.courses : [];
    const readyIds = courses.filter((c) => c && c.status === "ready").map((c) => c.id);

    // Fire a browser notification for genuinely-new ready transitions.
    try {
      if (prevReadyRef.current === null) {
        // First poll establishes the baseline — do not fire for pre-existing ready courses.
        prevReadyRef.current = new Set(readyIds);
        readyIds.forEach((id) => firedRef.current.add(id));
      } else {
        const prev = prevReadyRef.current;
        const canNotify = "Notification" in window && Notification.permission === "granted";
        for (const c of courses) {
          if (!c || c.status !== "ready") continue;
          if (prev.has(c.id) || firedRef.current.has(c.id)) continue;
          firedRef.current.add(c.id); // at most once per newly-ready course
          if (canNotify) {
            try {
              new Notification("SourceMind", { body: `‘${c.title || c.id}’ is ready to study` });
            } catch {
              // ignore notification construction errors
            }
          }
        }
        prevReadyRef.current = new Set(readyIds);
      }
    } catch {
      // never let notification logic break polling
    }

    setData({
      due_review_count: typeof res.due_review_count === "number" ? res.due_review_count : 0,
      courses,
    });
  }, []);

  usePolling(poll, { interval: POLL_MS, immediate: true });

  // Build the displayed notification list from current data.
  const notifications = useMemo(() => {
    const list = [];
    for (const c of data.courses) {
      if (!c) continue;
      const label = c.title || c.id;
      if (c.status === "ready") {
        list.push({
          key: `ready:${c.id}`,
          text: `‘${label}’ is ready to study`,
          href: `/courses/${encodeURIComponent(c.id)}`,
          isNew: !seen.includes(c.id),
        });
      } else if (c.status === "ingest_failed") {
        list.push({ key: `fail:${c.id}`, text: `‘${label}’ failed to import`, href: "/upload" });
      }
    }
    if (data.due_review_count > 0) {
      list.push({
        key: "due",
        text: `${data.due_review_count} card${data.due_review_count === 1 ? "" : "s"} due for review`,
        href: "/reviews",
      });
    }
    return list;
  }, [data, seen]);

  // Badge: unseen ready courses + a single bump when any reviews are due.
  const unseenReady = useMemo(
    () => data.courses.filter((c) => c && c.status === "ready" && !seen.includes(c.id)).length,
    [data, seen]
  );
  const badgeCount = unseenReady + (data.due_review_count > 0 ? 1 : 0);

  // Opening the panel acknowledges the currently-ready courses (clears the "new" highlight).
  // Compute outside any state updater so the localStorage write runs exactly once
  // (React Strict Mode double-invokes functional updaters in dev).
  const toggleOpen = useCallback(() => {
    const next = !open;
    setOpen(next);
    if (next) {
      const readyIds = data.courses.filter((c) => c && c.status === "ready").map((c) => c.id);
      const merged = Array.from(new Set([...seen, ...readyIds]));
      setSeen(merged);
      saveSeen(merged);
    }
  }, [open, seen, data]);

  return (
    <div style={{ position: "fixed", top: 14, right: 16, zIndex: 50 }}>
      <button
        type="button"
        aria-label="Notifications"
        aria-expanded={open}
        onClick={toggleOpen}
        style={{
          position: "relative",
          width: 40,
          height: 40,
          display: "grid",
          placeItems: "center",
          background: "var(--panel)",
          border: "1px solid var(--border)",
          borderRadius: 10,
          color: "var(--text)",
          cursor: "pointer",
        }}
      >
        <BellIcon />
        {badgeCount > 0 && (
          <span
            style={{
              position: "absolute",
              top: -5,
              right: -5,
              minWidth: 18,
              height: 18,
              padding: "0 5px",
              display: "grid",
              placeItems: "center",
              background: "var(--accent, #5b8cff)",
              color: "#fff",
              fontSize: 11,
              fontWeight: 700,
              borderRadius: 9,
              lineHeight: 1,
            }}
          >
            {badgeCount}
          </span>
        )}
      </button>

      {open && (
        <>
          {/* click-outside catcher */}
          <div
            onClick={() => setOpen(false)}
            style={{ position: "fixed", inset: 0, zIndex: 0 }}
          />
          <div
            role="menu"
            style={{
              position: "absolute",
              top: 48,
              right: 0,
              zIndex: 1,
              width: 300,
              maxHeight: "70vh",
              overflowY: "auto",
              background: "var(--panel)",
              border: "1px solid var(--border)",
              borderRadius: 12,
              boxShadow: "0 10px 30px rgba(0,0,0,0.25)",
              padding: 8,
            }}
          >
            <p
              className="muted"
              style={{
                margin: "4px 8px 8px",
                fontSize: 11,
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                fontWeight: 600,
              }}
            >
              Notifications
            </p>

            {notifications.length === 0 ? (
              <p className="muted" style={{ margin: "8px", fontSize: 14 }}>
                You&apos;re all caught up.
              </p>
            ) : (
              notifications.map((n) => (
                <Link
                  key={n.key}
                  href={n.href}
                  onClick={() => setOpen(false)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "9px 8px",
                    borderRadius: 8,
                    color: "var(--text)",
                    textDecoration: "none",
                    fontSize: 14,
                    lineHeight: 1.4,
                  }}
                >
                  <span
                    style={{
                      flexShrink: 0,
                      width: 7,
                      height: 7,
                      borderRadius: "50%",
                      background: n.isNew ? "var(--accent, #5b8cff)" : "transparent",
                      border: n.isNew ? "none" : "1px solid var(--border)",
                    }}
                  />
                  <span>{n.text}</span>
                </Link>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}
