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
  const initialCourseId = searchParams.get("course") || "";

  const [courses, setCourses] = useState([]);
  const [courseId, setCourseId] = useState(initialCourseId);
  const [dueCards, setDueCards] = useState([]); // [{q, a, section_id, card_index, ...}]
  const [current, setCurrent] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [loadingCourses, setLoadingCourses] = useState(true);
  const [loadingCards, setLoadingCards] = useState(false);
  const [grading, setGrading] = useState(false);
  const [error, setError] = useState(null);

  // Load course list on mount
  useEffect(() => {
    library
      .listCourses()
      .then((data) => setCourses(Array.isArray(data) ? data : (data?.courses || [])))
      .catch((err) => setError(err.message))
      .finally(() => setLoadingCourses(false));
  }, []);

  // Fetch due cards whenever the selected course changes
  const loadReviews = useCallback(async (id) => {
    if (!id) return;
    setLoadingCards(true);
    setError(null);
    setDueCards([]);
    setCurrent(0);
    setRevealed(false);
    try {
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

      // Join due rows to card text; skip out-of-range indices
      const cards = [];
      for (const row of dueRows) {
        const arr = chapterMap[row.section_id] || [];
        const card = arr[row.card_index];
        if (!card) continue;
        cards.push({ ...row, q: card.q, a: card.a });
      }
      setDueCards(cards);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingCards(false);
    }
  }, []);

  useEffect(() => {
    if (courseId) loadReviews(courseId);
  }, [courseId, loadReviews]);

  // Grade handler
  const handleGrade = async (correct) => {
    const card = dueCards[current];
    setGrading(true);
    try {
      await library.gradeReview(courseId, {
        section_id: card.section_id,
        card_index: card.card_index,
        correct,
      });
    } catch {
      // grade errors are non-fatal — advance regardless
    } finally {
      setGrading(false);
    }
    setCurrent((c) => c + 1);
    setRevealed(false);
  };

  const card = dueCards[current];
  const done = !loadingCards && courseId && current >= dueCards.length;

  return (
    <main>
      {/* ── Header + course picker ── */}
      <div style={{ marginBottom: 28 }}>
        <h2 style={{ margin: "0 0 16px" }}>Spaced Review</h2>

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
            <option value="">— select a course —</option>
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
      {courseId && loadingCards && <Spinner label="Loading due cards…" />}

      {/* ── Review session ── */}
      {courseId && !loadingCards && !error && (
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
                No cards due for this course. Check back later.
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

                  <div style={{ display: "flex", gap: 12 }}>
                    <button
                      onClick={() => handleGrade(true)}
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
                      }}
                    >
                      Got it
                    </button>
                    <button
                      onClick={() => handleGrade(false)}
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
                      }}
                    >
                      Missed
                    </button>
                  </div>
                </>
              )}
            </div>
          ) : null}
        </>
      )}

      {/* ── No course selected prompt ── */}
      {!courseId && !loadingCourses && (
        <p className="muted" style={{ marginTop: 8, fontSize: 14 }}>
          Select a course above to start your review session.
        </p>
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
