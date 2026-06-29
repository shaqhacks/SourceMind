"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { library } from "../../../../lib/api";
import { Badge, ErrorBanner, Spinner } from "../../../../components/ui";
import Markdown from "../../../../components/Markdown";

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
// Graded Test
// ---------------------------------------------------------------------------

function GradedTest({ courseId, sid, quiz }) {
  // mode: "idle" | "taking" | "result"
  const [mode, setMode] = useState("idle");
  const [selected, setSelected] = useState({});     // questionIndex -> answerIndex
  const [result, setResult] = useState(null);       // grading result from API
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [attempts, setAttempts] = useState(null);   // list of past attempts
  const [attemptsLoading, setAttemptsLoading] = useState(false);

  const loadAttempts = useCallback(async () => {
    setAttemptsLoading(true);
    try {
      const list = await library.sectionTestAttempts(courseId, sid);
      setAttempts(list);
    } catch {
      // non-fatal
    } finally {
      setAttemptsLoading(false);
    }
  }, [courseId, sid]);

  useEffect(() => { loadAttempts(); }, [loadAttempts]);

  if (!quiz || quiz.length === 0) return null;

  function startTest() {
    setSelected({});
    setResult(null);
    setSubmitError(null);
    setMode("taking");
  }

  function retake() {
    setSelected({});
    setResult(null);
    setSubmitError(null);
    setMode("taking");
  }

  async function submitTest() {
    setSubmitting(true);
    setSubmitError(null);
    const answers = quiz.map((_, i) => (selected[i] !== undefined ? selected[i] : -1));
    try {
      const res = await library.submitSectionTest(courseId, sid, answers);
      setResult(res);
      setMode("result");
      loadAttempts();
    } catch (err) {
      setSubmitError(err.message || "Submission failed.");
    } finally {
      setSubmitting(false);
    }
  }

  const panelStyle = {
    background: "var(--panel)",
    border: "1px solid var(--border)",
    borderRadius: 12,
    overflow: "hidden",
    marginBottom: 32,
  };

  const headerStyle = {
    padding: "14px 18px",
    borderBottom: "1px solid var(--border)",
    display: "flex",
    alignItems: "center",
    gap: 10,
  };

  // ── Idle: show start button + attempt history ────────────────────────────
  if (mode === "idle") {
    return (
      <div style={panelStyle}>
        <div style={headerStyle}>
          <span style={{ fontSize: 18 }}>📋</span>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Graded Test</h3>
          <span className="muted" style={{ fontSize: 13 }}>
            {quiz.length} question{quiz.length !== 1 ? "s" : ""} — scored and saved
          </span>
        </div>
        <div style={{ padding: "18px 18px 10px" }}>
          <p className="muted" style={{ margin: "0 0 16px", fontSize: 14 }}>
            Unlike the practice quiz, this test records your score. No instant feedback — results shown after submission.
          </p>
          <button onClick={startTest} style={{ margin: 0 }}>
            Take graded test
          </button>
        </div>
        {/* Attempt history */}
        <div style={{ padding: "10px 18px 18px" }}>
          <p style={{ margin: "0 0 8px", fontSize: 13, fontWeight: 700, color: "var(--muted)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
            Past attempts
          </p>
          {attemptsLoading && <Spinner label="Loading history…" />}
          {!attemptsLoading && attempts !== null && attempts.length === 0 && (
            <p className="muted" style={{ margin: 0, fontSize: 14, fontStyle: "italic" }}>No attempts yet.</p>
          )}
          {!attemptsLoading && attempts && attempts.length > 0 && (
            <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
              {attempts.map((a) => (
                <li key={a.id} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 14 }}>
                  <Badge tone={a.passed ? "ok" : "bad"} dot>{a.passed ? "Pass" : "Fail"}</Badge>
                  <span style={{ fontWeight: 600 }}>{a.correct}/{a.total}</span>
                  <span className="muted">{Math.round(a.score * 100)}%</span>
                  {a.created_at && (
                    <span className="muted" style={{ fontSize: 12 }}>
                      {new Date(a.created_at).toLocaleDateString()}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    );
  }

  // ── Taking: render questions with no feedback ────────────────────────────
  if (mode === "taking") {
    const allAnswered = quiz.every((_, i) => selected[i] !== undefined);
    return (
      <div style={panelStyle}>
        <div style={headerStyle}>
          <span style={{ fontSize: 18 }}>📋</span>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Graded Test</h3>
          <span className="muted" style={{ fontSize: 13 }}>
            {Object.keys(selected).length}/{quiz.length} answered
          </span>
        </div>
        <div style={{ padding: 18, display: "flex", flexDirection: "column", gap: 24 }}>
          {quiz.map((item, qi) => (
            <div key={qi}>
              <p style={{ margin: "0 0 10px", fontWeight: 600, fontSize: 15, lineHeight: 1.5 }}>
                {qi + 1}. {item.q}
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {item.options.map((opt, oi) => {
                  const isSelected = selected[qi] === oi;
                  return (
                    <label
                      key={oi}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 10,
                        padding: "9px 13px",
                        border: `1px solid ${isSelected ? "rgba(91,140,255,0.5)" : "var(--border)"}`,
                        borderRadius: 8,
                        background: isSelected ? "rgba(91,140,255,0.08)" : "transparent",
                        cursor: "pointer",
                        fontSize: 14,
                        lineHeight: 1.5,
                        userSelect: "none",
                      }}
                    >
                      <input
                        type="radio"
                        name={`q${qi}`}
                        value={oi}
                        checked={isSelected}
                        onChange={() => setSelected((prev) => ({ ...prev, [qi]: oi }))}
                        style={{ margin: 0, accentColor: "var(--accent, #5b8cff)" }}
                      />
                      {opt}
                    </label>
                  );
                })}
              </div>
            </div>
          ))}
          {submitError && <ErrorBanner error={submitError} />}
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <button
              onClick={submitTest}
              disabled={submitting || !allAnswered}
              style={{ margin: 0 }}
            >
              {submitting ? "Submitting…" : "Submit test"}
            </button>
            <button
              onClick={() => setMode("idle")}
              disabled={submitting}
              style={{ margin: 0, background: "transparent", border: "1px solid var(--border)", color: "var(--text)" }}
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Result: score summary + per-question review ──────────────────────────
  if (mode === "result" && result) {
    const pct = Math.round(result.score * 100);
    const passTone = result.passed ? "ok" : "bad";
    return (
      <div style={panelStyle}>
        <div style={headerStyle}>
          <span style={{ fontSize: 18 }}>📋</span>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Graded Test — Results</h3>
        </div>
        {/* Score summary */}
        <div style={{ padding: "20px 18px", borderBottom: "1px solid var(--border)", display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap" }}>
          <span style={{ fontSize: 32, fontWeight: 800, lineHeight: 1 }}>
            {result.correct}/{result.total}
          </span>
          <span style={{ fontSize: 24, fontWeight: 700, color: result.passed ? "var(--ok)" : "var(--bad, #f85149)" }}>
            {pct}%
          </span>
          <Badge tone={passTone} dot>{result.passed ? "Passed" : "Failed"}</Badge>
        </div>
        {/* Per-question review */}
        <div style={{ padding: 18, display: "flex", flexDirection: "column", gap: 18 }}>
          {(result.results || []).map((item, i) => (
            <div
              key={i}
              style={{
                padding: "14px 16px",
                border: `1px solid ${item.correct ? "rgba(63,185,80,0.3)" : "rgba(248,81,73,0.3)"}`,
                borderRadius: 10,
                background: item.correct ? "rgba(63,185,80,0.04)" : "rgba(248,81,73,0.04)",
              }}
            >
              <p style={{ margin: "0 0 8px", fontWeight: 600, fontSize: 14 }}>
                <Badge tone={item.correct ? "ok" : "bad"}>{item.correct ? "✓" : "✗"}</Badge>
                {" "}{i + 1}. {item.q}
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 8 }}>
                {(item.options || []).map((opt, oi) => {
                  const isYours = item.your_index === oi;
                  const isCorrect = item.answer_index === oi;
                  let color = "var(--text)";
                  if (isCorrect) color = "var(--ok)";
                  else if (isYours && !isCorrect) color = "var(--bad, #f85149)";
                  return (
                    <div key={oi} style={{ fontSize: 13, color, fontWeight: isCorrect || isYours ? 600 : 400 }}>
                      {isCorrect ? "✓ " : isYours ? "✗ " : "  "}{opt}
                      {isYours && !isCorrect && " (your answer)"}
                      {isCorrect && isYours && " (correct)"}
                      {isCorrect && !isYours && " (correct answer)"}
                    </div>
                  );
                })}
              </div>
              {item.explain && (
                <p className="muted" style={{ margin: 0, fontSize: 13, fontStyle: "italic" }}>
                  {item.explain}
                </p>
              )}
            </div>
          ))}
          <button onClick={retake} style={{ margin: 0, alignSelf: "flex-start" }}>
            Retake test
          </button>
        </div>
      </div>
    );
  }

  return null;
}

// ---------------------------------------------------------------------------
// Tutor Chat
// ---------------------------------------------------------------------------

function TutorChat({ courseId, sid }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send(e) {
    e.preventDefault();
    const q = input.trim();
    if (!q || busy) return;
    setInput("");
    setBusy(true);
    setMessages((prev) => [...prev, { role: "student", text: q }]);
    try {
      const { answer } = await library.chat(courseId, sid, q);
      setMessages((prev) => [...prev, { role: "tutor", text: answer }]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "tutor", text: `Error: ${err.message}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{
      background: "var(--panel)",
      border: "1px solid var(--border)",
      borderRadius: 12,
      overflow: "hidden",
      display: "flex",
      flexDirection: "column",
      maxHeight: 520,
    }}>
      <div style={{
        padding: "14px 18px",
        borderBottom: "1px solid var(--border)",
        display: "flex",
        alignItems: "center",
        gap: 10,
      }}>
        <span style={{ fontSize: 18 }}>💬</span>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Tutor Chat</h3>
        <span className="muted" style={{ fontSize: 13 }}>Ask anything about this chapter</span>
      </div>

      <div style={{
        flex: 1,
        overflowY: "auto",
        padding: "14px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 10,
        minHeight: 120,
      }}>
        {messages.length === 0 && (
          <p className="muted" style={{ margin: 0, fontSize: 14, fontStyle: "italic" }}>
            No messages yet. Ask a question below.
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            style={{
              alignSelf: m.role === "student" ? "flex-end" : "flex-start",
              maxWidth: "90%",
              background:
                m.role === "student"
                  ? "rgba(91,140,255,0.14)"
                  : "#0e1422",
              border:
                m.role === "student"
                  ? "1px solid rgba(91,140,255,0.35)"
                  : "1px solid var(--border)",
              borderRadius: 10,
              padding: "9px 13px",
              fontSize: 14,
              lineHeight: 1.6,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
            }}
          >
            {m.text}
          </div>
        ))}
        {busy && (
          <div style={{
            alignSelf: "flex-start",
            color: "var(--muted)",
            fontSize: 13,
            fontStyle: "italic",
            padding: "4px 0",
          }}>
            Thinking…
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={send}
        style={{
          display: "grid",
          gridTemplateColumns: "1fr auto",
          gap: 8,
          padding: "12px 14px",
          borderTop: "1px solid var(--border)",
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about this chapter…"
          disabled={busy}
          style={{ margin: 0 }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(e);
            }
          }}
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          style={{ margin: 0, padding: "10px 18px" }}
        >
          Send
        </button>
      </form>
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
  const [scrollProgress, setScrollProgress] = useState(0);

  // Reading-progress bar
  useEffect(() => {
    function onScroll() {
      const el = document.documentElement;
      const scrolled = el.scrollTop || document.body.scrollTop;
      const total = el.scrollHeight - el.clientHeight;
      setScrollProgress(total > 0 ? scrolled / total : 0);
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

  async function markComplete() {
    setCompleting(true);
    try {
      await library.setProgress(id, sid, true);
      setCompleted(true);
    } catch (err) {
      // non-fatal — show inline
      console.error("Progress update failed:", err.message);
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

      {/* ── Chapter body ── */}
      <article style={{ marginBottom: 48 }}>
        <Markdown source={chapter.body_md || ""} />
      </article>

      {/* ── Mark complete ── */}
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
        marginBottom: 32,
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

      {/* ── Graded test ── */}
      <GradedTest courseId={id} sid={sid} quiz={chapter.quiz || []} />

      {/* ── Tutor chat ── */}
      <TutorChat courseId={id} sid={sid} />
    </main>
  );
}
