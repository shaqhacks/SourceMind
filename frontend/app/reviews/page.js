"use client";

import { useCallback, useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { library } from "../lib/api";
import { ErrorBanner, Spinner } from "../components/ui";

// ---------------------------------------------------------------------------
// Inner component — uses useSearchParams (must be wrapped in Suspense)
// ---------------------------------------------------------------------------

function ReviewsInner() {
  const searchParams = useSearchParams();
  // Default to "" (All subjects) unless a ?course= param is present.
  const initialCourseId = searchParams.get("course") || "";

  const [courses, setCourses] = useState([]);
  const [courseId, setCourseId] = useState(initialCourseId);
  const [dueCards, setDueCards] = useState([]); // [{q, a, section_id, card_index, course_id, course_title?}]
  const [current, setCurrent] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [loadingCourses, setLoadingCourses] = useState(true);
  // Start true: we always auto-load on mount, so avoid a flash of "All caught up".
  const [loadingCards, setLoadingCards] = useState(true);
  const [grading, setGrading] = useState(false);
  const [error, setError] = useState(null);
  const [stats, setStats] = useState(null);
  const [statsError, setStatsError] = useState(null);

  const isAllMode = !courseId; // "" → All subjects

  // Load stats. Non-blocking for the review session itself, but surface the
  // failure when we have nothing to show rather than leaving the stats
  // header silently empty.
  const loadStats = useCallback(() => {
    library
      .reviewStats()
      .then((s) => {
        setStats(s);
        setStatsError(null);
      })
      .catch((err) => setStatsError(err.message || "Failed to load review stats."));
  }, []);

  // Load course list on mount; also load stats on mount
  useEffect(() => {
    library
      .listCourses()
      .then((data) => setCourses(Array.isArray(data) ? data : (data?.courses || [])))
      .catch((err) => setError(err.message))
      .finally(() => setLoadingCourses(false));
  }, []);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  // Fetch due cards whenever the selected course changes.
  // id falsy → All subjects (aggregate endpoint already includes q/a/course_*).
  const loadReviews = useCallback(async (id) => {
    setLoadingCards(true);
    setError(null);
    setDueCards([]);
    setCurrent(0);
    setRevealed(false);
    try {
      if (!id) {
        // All subjects: cards already carry q, a, course_id, course_title.
        const cards = await library.dueReviewsAll();
        setDueCards(Array.isArray(cards) ? cards : []);
        return;
      }

      // Single course: fetch due rows, then join to chapter card text.
      const dueRows = await library.dueReviews(id);
      if (!dueRows || dueRows.length === 0) {
        setDueCards([]);
        return;
      }

      // Fetch each unique section once and cache its cards array
      const uniqueSids = [...new Set(dueRows.map((r) => r.section_id))];
      const chapterMap = {};
      await Promise.all(
        uniqueSids.map(async (sid) => {
          try {
            const ch = await library.getChapter(id, sid);
            chapterMap[sid] = ch.cards || [];
          } catch {
            chapterMap[sid] = [];
          }
        })
      );

      // Join due rows to card text; skip out-of-range indices.
      // Stamp course_id = id so grading works uniformly with All mode.
      const cards = [];
      for (const row of dueRows) {
        const arr = chapterMap[row.section_id] || [];
        const card = arr[row.card_index];
        if (!card) continue;
        cards.push({ ...row, course_id: id, q: card.q, a: card.a });
      }
      setDueCards(cards);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingCards(false);
    }
  }, []);

  useEffect(() => {
    loadReviews(courseId);
  }, [courseId, loadReviews]);

  // Grade handler — grade against the card's own course (All mode spans courses).
  const handleGrade = async (quality) => {
    const card = dueCards[current];
    setGrading(true);
    setError(null);
    try {
      await library.gradeReview(card.course_id || courseId, {
        section_id: card.section_id,
        card_index: card.card_index,
        quality,
      });
    } catch (err) {
      setError(err.message); // show error, do NOT advance — let the user retry
      setGrading(false);
      return;
    }
    setGrading(false);
    // optimistically bump today's progress, then refresh stats
    setStats((s) => (s ? { ...s, reviewed_today: s.reviewed_today + 1 } : s));
    loadStats(); // refresh from server (non-blocking)
    setCurrent((c) => c + 1);
    setRevealed(false);
  };

  const card = dueCards[current];
  const done = !loadingCards && current >= dueCards.length;

  return (
    <main>
      {/* ── Header + course picker ── */}
      <div style={{ marginBottom: 28 }}>
        <h2 style={{ margin: "0 0 16px" }}>Spaced Review</h2>

        {/* Only show the stats-load error when we have nothing else to display —
            a later background refresh failing shouldn't blank out working stats. */}
        {!stats && statsError && <ErrorBanner error={statsError} />}

        {/* ── Stats header (non-null guard) ── */}
        {stats && (
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              gap: 10,
              marginBottom: 20,
            }}
          >
            {/* Streak */}
            <div
              style={{
                background: "var(--panel)",
                border: "1px solid var(--border)",
                borderRadius: 10,
                padding: "10px 16px",
                minWidth: 100,
              }}
            >
              <div style={{ fontSize: 18, marginBottom: 2 }}>🔥</div>
              <div style={{ fontSize: 15, fontWeight: 600, color: "var(--text)" }}>
                {stats.streak_days}-day streak
              </div>
            </div>

            {/* Today's progress */}
            <div
              style={{
                background: "var(--panel)",
                border: "1px solid var(--border)",
                borderRadius: 10,
                padding: "10px 16px",
                minWidth: 140,
              }}
            >
              <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
                Today
              </div>
              <div style={{ fontSize: 15, fontWeight: 600, color: "var(--text)", marginBottom: 6 }}>
                {stats.reviewed_today}/{stats.daily_goal} today
              </div>
              <div
                style={{
                  height: 4,
                  borderRadius: 2,
                  background: "var(--border)",
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    height: "100%",
                    borderRadius: 2,
                    background: "var(--accent, #5b8cff)",
                    width: `${stats.daily_goal > 0 ? Math.min(100, (stats.reviewed_today / stats.daily_goal) * 100) : 0}%`,
                  }}
                />
              </div>
            </div>

            {/* Due count */}
            <div
              style={{
                background: "var(--panel)",
                border: "1px solid var(--border)",
                borderRadius: 10,
                padding: "10px 16px",
                minWidth: 90,
              }}
            >
              <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
                Due
              </div>
              <div style={{ fontSize: 15, fontWeight: 600, color: "var(--text)" }}>
                {stats.due_count} due
              </div>
            </div>

            {/* Mastered count */}
            <div
              style={{
                background: "var(--panel)",
                border: "1px solid var(--border)",
                borderRadius: 10,
                padding: "10px 16px",
                minWidth: 110,
              }}
            >
              <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
                Mastered
              </div>
              <div style={{ fontSize: 15, fontWeight: 600, color: "var(--text)" }}>
                {stats.mastered_count} mastered
              </div>
            </div>
          </div>
        )}

        {loadingCourses ? (
          <Spinner label="Loading courses…" />
        ) : (
          <select
            value={courseId}
            onChange={(e) => setCourseId(e.target.value)}
            style={{
              background: "var(--panel)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              color: "var(--text)",
              padding: "8px 12px",
              fontSize: 14,
              minWidth: 280,
              cursor: "pointer",
            }}
          >
            <option value="">All subjects</option>
            {courses.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title || c.id}
              </option>
            ))}
          </select>
        )}
      </div>

      <ErrorBanner error={error} />

      {/* ── Loading cards ── */}
      {loadingCards && <Spinner label="Loading due cards…" />}

      {/* ── Review session ── */}
      {!loadingCards && !error && (
        <>
          {done ? (
            /* All caught up */
            <div
              style={{
                background: "var(--panel)",
                border: "1px solid var(--border)",
                borderRadius: 16,
                padding: "48px 32px",
                textAlign: "center",
              }}
            >
              <div style={{ fontSize: 40, marginBottom: 12 }}>✅</div>
              <h3 style={{ margin: "0 0 8px" }}>All caught up!</h3>
              <p className="muted" style={{ margin: 0 }}>
                {isAllMode
                  ? "No cards due right now."
                  : "No cards due for this course. Check back later."}
              </p>
            </div>
          ) : card ? (
            /* Flash card */
            <div
              style={{
                background: "var(--panel)",
                border: "1px solid var(--border)",
                borderRadius: 16,
                padding: "32px",
                maxWidth: 620,
              }}
            >
              {/* Progress indicator */}
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: 13,
                  marginBottom: 20,
                }}
              >
                <span className="muted">
                  Card {current + 1} of {dueCards.length}
                </span>
                <span className="muted">
                  {dueCards.length - current - 1} remaining
                </span>
              </div>

              {/* Subject label (All subjects mode) */}
              {isAllMode && card.course_title && (
                <p
                  className="muted"
                  style={{
                    margin: "0 0 10px",
                    fontSize: 12,
                    fontWeight: 600,
                    color: "var(--accent, #5b8cff)",
                  }}
                >
                  {card.course_title}
                </p>
              )}

              {/* Question */}
              <div style={{ marginBottom: 24 }}>
                <p
                  className="muted"
                  style={{ margin: "0 0 6px", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em" }}
                >
                  Question
                </p>
                <p style={{ margin: 0, fontSize: 17, lineHeight: 1.55 }}>{card.q}</p>
              </div>

              {/* Reveal / Answer */}
              {!revealed ? (
                <button
                  onClick={() => setRevealed(true)}
                  style={{
                    background: "rgba(91,140,255,0.12)",
                    border: "1px solid rgba(91,140,255,0.3)",
                    borderRadius: 8,
                    color: "var(--accent, #5b8cff)",
                    padding: "10px 20px",
                    fontSize: 14,
                    cursor: "pointer",
                    width: "100%",
                  }}
                >
                  Show answer
                </button>
              ) : (
                <>
                  <div
                    style={{
                      borderTop: "1px solid var(--border)",
                      paddingTop: 20,
                      marginBottom: 24,
                    }}
                  >
                    <p
                      className="muted"
                      style={{ margin: "0 0 6px", fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em" }}
                    >
                      Answer
                    </p>
                    <p style={{ margin: 0, fontSize: 15, lineHeight: 1.6 }}>{card.a}</p>
                  </div>

                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    {/* Again = 0, red */}
                    <button
                      onClick={() => handleGrade(0)}
                      disabled={grading}
                      style={{
                        flex: 1,
                        background: "rgba(255,69,58,0.10)",
                        border: "1px solid rgba(255,69,58,0.3)",
                        borderRadius: 8,
                        color: "#ff453a",
                        padding: "11px 0",
                        fontSize: 14,
                        fontWeight: 600,
                        cursor: grading ? "not-allowed" : "pointer",
                        opacity: grading ? 0.6 : 1,
                        minWidth: 70,
                      }}
                    >
                      Again
                    </button>
                    {/* Hard = 1, orange */}
                    <button
                      onClick={() => handleGrade(1)}
                      disabled={grading}
                      style={{
                        flex: 1,
                        background: "rgba(255,159,10,0.10)",
                        border: "1px solid rgba(255,159,10,0.3)",
                        borderRadius: 8,
                        color: "#ff9f0a",
                        padding: "11px 0",
                        fontSize: 14,
                        fontWeight: 600,
                        cursor: grading ? "not-allowed" : "pointer",
                        opacity: grading ? 0.6 : 1,
                        minWidth: 70,
                      }}
                    >
                      Hard
                    </button>
                    {/* Good = 2, green */}
                    <button
                      onClick={() => handleGrade(2)}
                      disabled={grading}
                      style={{
                        flex: 1,
                        background: "rgba(52,199,89,0.12)",
                        border: "1px solid rgba(52,199,89,0.35)",
                        borderRadius: 8,
                        color: "#34c759",
                        padding: "11px 0",
                        fontSize: 14,
                        fontWeight: 600,
                        cursor: grading ? "not-allowed" : "pointer",
                        opacity: grading ? 0.6 : 1,
                        minWidth: 70,
                      }}
                    >
                      Good
                    </button>
                    {/* Easy = 3, blue */}
                    <button
                      onClick={() => handleGrade(3)}
                      disabled={grading}
                      style={{
                        flex: 1,
                        background: "rgba(91,140,255,0.12)",
                        border: "1px solid rgba(91,140,255,0.3)",
                        borderRadius: 8,
                        color: "var(--accent, #5b8cff)",
                        padding: "11px 0",
                        fontSize: 14,
                        fontWeight: 600,
                        cursor: grading ? "not-allowed" : "pointer",
                        opacity: grading ? 0.6 : 1,
                        minWidth: 70,
                      }}
                    >
                      Easy
                    </button>
                  </div>
                </>
              )}
            </div>
          ) : null}
        </>
      )}
    </main>
  );
}

// ---------------------------------------------------------------------------
// Default export — wraps ReviewsInner in Suspense (required for useSearchParams)
// ---------------------------------------------------------------------------

export default function Reviews() {
  return (
    <Suspense
      fallback={
        <main>
          <Spinner label="Loading…" />
        </main>
      }
    >
      <ReviewsInner />
    </Suspense>
  );
}
