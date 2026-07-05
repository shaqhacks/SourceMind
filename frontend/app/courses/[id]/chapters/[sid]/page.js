"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { library } from "../../../../lib/api";
import { usePolling } from "../../../../lib/usePolling";
import { Badge, ErrorBanner, Spinner } from "../../../../components/ui";
import Markdown from "../../../../components/Markdown";
import GradedTest from "../../../../components/GradedTest";
import Chat from "../../../../components/Chat";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const IMPORTANCE_TONE = {
  core: "ok",
  essential: "ok",
  important: "info",
  supplemental: "muted",
  optional: "muted",
  advanced: "warn",
};

function importanceTone(imp) {
  return IMPORTANCE_TONE[String(imp).toLowerCase()] || "muted";
}

function wordCountLabel(n) {
  if (!n) return null;
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k words` : `${n} words`;
}

/** Find previous and next section_ids relative to `currentSid` in a flat chapters array. */
function findSiblings(chapters, currentSid) {
  if (!chapters) return { prev: null, next: null };
  const idx = chapters.findIndex((c) => c.section_id === currentSid);
  if (idx === -1) return { prev: null, next: null };
  return {
    prev: idx > 0 ? chapters[idx - 1] : null,
    next: idx < chapters.length - 1 ? chapters[idx + 1] : null,
  };
}

// ---------------------------------------------------------------------------
// View-mode toggle (Original source ⇄ Guided lesson)
// ---------------------------------------------------------------------------

const viewToggleBtnBase = {
  margin: 0,
  padding: "7px 14px",
  borderRadius: 8,
  fontSize: 13,
  fontWeight: 500,
  cursor: "pointer",
  border: "1px solid var(--border)",
  transition: "background 0.12s, color 0.12s",
};

const viewToggleActive = {
  background: "rgba(91,140,255,0.18)",
  border: "1px solid rgba(91,140,255,0.40)",
  color: "var(--accent, #5b8cff)",
};

const viewToggleInactive = {
  background: "transparent",
  color: "var(--muted)",
};

function ViewToggle({ mode, onChange }) {
  return (
    <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
      <button
        onClick={() => onChange("source")}
        style={{ ...viewToggleBtnBase, ...(mode === "source" ? viewToggleActive : viewToggleInactive) }}
      >
        Original source
      </button>
      <button
        onClick={() => onChange("lesson")}
        style={{ ...viewToggleBtnBase, ...(mode === "lesson" ? viewToggleActive : viewToggleInactive) }}
      >
        Guided lesson
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chapter page
// ---------------------------------------------------------------------------

export default function ChapterPage() {
  const params = useParams();
  const id = decodeURIComponent(params.id);
  const sid = decodeURIComponent(params.sid);

  const [chapter, setChapter] = useState(null);
  const [siblings, setSiblings] = useState({ prev: null, next: null });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [completing, setCompleting] = useState(false);
  const [completed, setCompleted] = useState(false);
  const [completeError, setCompleteError] = useState(null);
  const [scrollProgress, setScrollProgress] = useState(0);

  // Study (quiz/cards) lazy-load state
  const [studyLoading, setStudyLoading] = useState(false);
  const [studyError, setStudyError] = useState(null);

  // Guided lesson state
  const [lessonGenerating, setLessonGenerating] = useState(false);
  const [lessonPolling, setLessonPolling] = useState(false);
  const [lessonError, setLessonError] = useState(null);
  const [viewMode, setViewMode] = useState("source"); // "source" | "lesson"

  // Reading-progress bar — rAF-throttled so scroll doesn't trigger a state
  // update (and re-render) on every native scroll event.
  useEffect(() => {
    let ticking = false;
    function computeProgress() {
      const el = document.documentElement;
      const scrolled = el.scrollTop || document.body.scrollTop;
      const total = el.scrollHeight - el.clientHeight;
      setScrollProgress(total > 0 ? scrolled / total : 0);
      ticking = false;
    }
    function onScroll() {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(computeProgress);
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Fetch chapter and course outline in parallel
      const [ch, courseData] = await Promise.all([
        library.getChapter(id, sid),
        library.getCourse(id).catch(() => null),
      ]);
      setChapter(ch);
      setCompleted(!!ch.completed);
      if (courseData?.chapters) {
        const planItems = courseData.plan || [];
        const orderMap = {};
        planItems.forEach((item) => {
          if (item.section_id != null) orderMap[item.section_id] = item.order ?? Infinity;
        });
        const sorted = [...courseData.chapters].sort((a, b) => {
          const oa = orderMap[a.section_id] ?? Infinity;
          const ob = orderMap[b.section_id] ?? Infinity;
          return oa - ob;
        });
        setSiblings(findSiblings(sorted, sid));
      }
    } catch (err) {
      setError(err.message || "Failed to load chapter.");
    } finally {
      setLoading(false);
    }
  }, [id, sid]);

  useEffect(() => { load(); }, [load]);

  // Poll while a guided-lesson generation is in flight (either resumed from a
  // page load that finds lesson_status==="generating", or kicked off by
  // handleGenerateLesson below) — single poller shared by both triggers.
  usePolling(
    async () => {
      const updated = await library.getChapter(id, sid);
      if (updated.lesson_status === "ready") {
        setChapter(updated);
        setViewMode("lesson");
        setLessonGenerating(false);
        setLessonPolling(false);
        return true;
      }
      if (updated.lesson_status === "failed") {
        setLessonError("Lesson generation failed. Try again.");
        setLessonGenerating(false);
        setLessonPolling(false);
        return true;
      }
      return false;
    },
    { interval: 3000, enabled: lessonPolling }
  );

  // After chapter loads: set view mode, resume lesson poll if needed, lazy-load study
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!chapter) return;

    // Default to lesson view if lesson is already available
    if (chapter.lesson_md) {
      setViewMode("lesson");
    }

    // Resume lesson polling if generation was already in progress
    if (chapter.lesson_status === "generating" && !lessonPolling) {
      setLessonGenerating(true);
      setLessonPolling(true);
    }

    // Lazy study: call ensureStudy when quiz is empty
    if (!chapter.quiz || chapter.quiz.length === 0) {
      setStudyLoading(true);
      setStudyError(null);
      library
        .ensureStudy(id, sid)
        .then((updated) => setChapter(updated))
        .catch((err) => setStudyError(err.message || "Failed to prepare study tools."))
        .finally(() => setStudyLoading(false));
    }
  }, [chapter?.section_id]); // fire once per chapter identity; id/sid are stable

  /** Trigger guided-lesson generation and start polling until ready. */
  async function handleGenerateLesson() {
    if (lessonPolling) return; // already polling
    setLessonError(null);
    setLessonGenerating(true);
    try {
      await library.generateLesson(id, sid);
      setLessonPolling(true);
    } catch (err) {
      setLessonError(err.message || "Failed to start lesson generation.");
      setLessonGenerating(false);
    }
  }

  const sendTutorChat = useCallback((q) => library.chat(id, sid, q), [id, sid]);

  async function markComplete() {
    setCompleting(true);
    setCompleteError(null);
    try {
      await library.setProgress(id, sid, true);
      setCompleted(true);
    } catch (err) {
      setCompleteError(err.status === 404 ? "Chapter not found." : err.message || "Failed to save progress. Try again.");
    } finally {
      setCompleting(false);
    }
  }

  // ── Loading / error ─────────────────────────────────────────────────────
  if (loading) {
    return (
      <main>
        <div style={{ marginBottom: 16 }}>
          <Link href={`/courses/${encodeURIComponent(id)}`} className="muted">
            ← Table of Contents
          </Link>
        </div>
        <Spinner label="Loading chapter…" />
      </main>
    );
  }

  if (error || !chapter) {
    return (
      <main>
        <div style={{ marginBottom: 16 }}>
          <Link href={`/courses/${encodeURIComponent(id)}`} className="muted">
            ← Table of Contents
          </Link>
        </div>
        <ErrorBanner error={error || "Chapter not found."} />
      </main>
    );
  }

  const wc = wordCountLabel(chapter.word_count);
  const hasLesson = !!chapter.lesson_md;
  const contentMd = viewMode === "lesson" && hasLesson
    ? chapter.lesson_md
    : (chapter.body_md || "");

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <main>
      {/* ── Reading progress bar ── */}
      <div
        style={{
          position: "fixed",
          top: 0,
          left: 0,
          height: 3,
          width: `${scrollProgress * 100}%`,
          background: "var(--accent, #5b8cff)",
          zIndex: 60,
          transition: "width 0.1s linear",
          pointerEvents: "none",
        }}
      />

      {/* ── Top navigation bar ── */}
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        flexWrap: "wrap",
        gap: 12,
        marginBottom: 28,
        paddingBottom: 16,
        borderBottom: "1px solid var(--border)",
      }}>
        <Link
          href={`/courses/${encodeURIComponent(id)}`}
          className="muted"
          style={{ fontSize: 14 }}
        >
          ← Table of Contents
        </Link>

        <span style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {siblings.prev && (
            <Link
              href={`/courses/${encodeURIComponent(id)}/chapters/${encodeURIComponent(siblings.prev.section_id)}`}
              style={{ fontSize: 14 }}
            >
              ← {siblings.prev.title || "Previous"}
            </Link>
          )}
          {siblings.prev && siblings.next && (
            <span className="muted" style={{ fontSize: 13 }}>·</span>
          )}
          {siblings.next && (
            <Link
              href={`/courses/${encodeURIComponent(id)}/chapters/${encodeURIComponent(siblings.next.section_id)}`}
              style={{ fontSize: 14 }}
            >
              {siblings.next.title || "Next"} →
            </Link>
          )}
        </span>
      </div>

      {/* ── Chapter header ── */}
      <header style={{ marginBottom: 32 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 12, flexWrap: "wrap" }}>
          {chapter.importance && (
            <Badge tone={importanceTone(chapter.importance)} dot>
              {chapter.importance}
            </Badge>
          )}
          {chapter.status && chapter.status !== "ready" && (
            <Badge tone="muted">{chapter.status.replace(/_/g, " ")}</Badge>
          )}
          {completed && (
            <Badge tone="ok" dot>
              completed
            </Badge>
          )}
          {wc && (
            <span className="muted" style={{ fontSize: 13 }}>{wc}</span>
          )}
        </div>

        <h1 style={{ margin: "0 0 8px", fontSize: 32, fontWeight: 800, lineHeight: 1.2 }}>
          {chapter.title}
        </h1>

        {chapter.objectives && chapter.objectives.length > 0 && (
          <div style={{
            marginTop: 16,
            background: "var(--panel)",
            border: "1px solid var(--border)",
            borderRadius: 10,
            padding: "14px 18px",
          }}>
            <p style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
              Learning objectives
            </p>
            <ul style={{ margin: 0, paddingLeft: 20 }}>
              {chapter.objectives.map((obj, i) => (
                <li key={i} style={{ marginBottom: 4, fontSize: 15, lineHeight: 1.6 }}>
                  {obj}
                </li>
              ))}
            </ul>
          </div>
        )}
      </header>

      {/* ── View toggle + lesson generation controls ── */}
      {hasLesson ? (
        <ViewToggle mode={viewMode} onChange={setViewMode} />
      ) : lessonGenerating ? (
        <p className="muted" style={{ marginBottom: 20, fontSize: 14 }}>
          Generating guided lesson… (30–60 s)
        </p>
      ) : (
        <div style={{ marginBottom: 20, display: "flex", flexDirection: "column", gap: 8, alignItems: "flex-start" }}>
          {lessonError && <ErrorBanner error={lessonError} />}
          <button onClick={handleGenerateLesson} style={{ margin: 0 }}>
            {lessonError ? "Retry guided lesson" : "Generate guided lesson"}
          </button>
        </div>
      )}

      {/* ── Chapter body (source or lesson) ── */}
      <article style={{ marginBottom: 48 }}>
        <Markdown source={contentMd} />
      </article>

      {/* ── Mark complete ── */}
      <div style={{ marginBottom: 32 }}>
        {completeError && (
          <div style={{ marginBottom: 12 }}>
            <ErrorBanner error={completeError} />
          </div>
        )}
        <div style={{
          padding: "20px 24px",
          background: "var(--panel)",
          border: `1px solid ${completed ? "rgba(63,185,80,0.35)" : "var(--border)"}`,
          borderRadius: 12,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          flexWrap: "wrap",
          gap: 12,
        }}>
          <div>
            <p style={{ margin: 0, fontWeight: 600, fontSize: 15 }}>
              {completed ? "You've completed this chapter." : "Finished reading?"}
            </p>
            {!completed && (
              <p className="muted" style={{ margin: "3px 0 0", fontSize: 14 }}>
                Mark it done to track your progress.
              </p>
            )}
          </div>
          {!completed ? (
            <button
              onClick={markComplete}
              disabled={completing}
              style={{ margin: 0 }}
            >
              {completing ? "Saving…" : "Mark complete ✓"}
            </button>
          ) : (
            <span style={{
              color: "var(--ok)",
              fontWeight: 700,
              fontSize: 18,
            }}>
              ✓ Done
            </span>
          )}
        </div>
      </div>

      {/* ── Bottom chapter navigation ── */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        gap: 12,
        marginBottom: 48,
        flexWrap: "wrap",
      }}>
        {siblings.prev ? (
          <Link
            href={`/courses/${encodeURIComponent(id)}/chapters/${encodeURIComponent(siblings.prev.section_id)}`}
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 2,
              padding: "12px 18px",
              background: "var(--panel)",
              border: "1px solid var(--border)",
              borderRadius: 10,
              minWidth: 140,
              textDecoration: "none",
              color: "var(--text)",
            }}
          >
            <span className="muted" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em" }}>← Previous</span>
            <span style={{ fontWeight: 600, fontSize: 15 }}>{siblings.prev.title}</span>
          </Link>
        ) : <span />}

        {siblings.next ? (
          <Link
            href={`/courses/${encodeURIComponent(id)}/chapters/${encodeURIComponent(siblings.next.section_id)}`}
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "flex-end",
              gap: 2,
              padding: "12px 18px",
              background: "var(--panel)",
              border: "1px solid var(--border)",
              borderRadius: 10,
              minWidth: 140,
              textDecoration: "none",
              color: "var(--text)",
            }}
          >
            <span className="muted" style={{ fontSize: 12, textTransform: "uppercase", letterSpacing: "0.05em" }}>Next →</span>
            <span style={{ fontWeight: 600, fontSize: 15 }}>{siblings.next.title}</span>
          </Link>
        ) : <span />}
      </div>

      {/* ── Study tools ── */}
      {studyLoading && (
        <div style={{ marginBottom: 24 }}>
          <Spinner label="Preparing study tools…" />
        </div>
      )}
      {studyError && (
        <div style={{ marginBottom: 16 }}>
          <ErrorBanner error={studyError} />
        </div>
      )}

      {/* ── Graded test (quiz populated lazily by ensureStudy) ── */}
      <GradedTest courseId={id} sid={sid} quiz={chapter.quiz || []} />

      {/* ── Tutor chat ── */}
      <div style={{ marginBottom: 32 }}>
        <Chat
          variant="card"
          icon="💬"
          title="Tutor Chat"
          subtitle="Ask anything about this chapter"
          placeholder="Ask a question about this chapter…"
          sendFn={sendTutorChat}
        />
      </div>
    </main>
  );
}
