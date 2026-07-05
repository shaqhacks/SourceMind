"use client";

import { useCallback, useEffect, useState } from "react";
import { library } from "../lib/api";
import { Badge, ErrorBanner, Spinner } from "./ui";

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

export default function GradedTest({ courseId, sid, quiz }) {
  // mode: "idle" | "taking" | "result"
  const [mode, setMode] = useState("idle");
  const [selected, setSelected] = useState({});     // questionIndex -> answerIndex
  const [result, setResult] = useState(null);       // grading result from API
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [attempts, setAttempts] = useState(null);   // list of past attempts
  const [attemptsLoading, setAttemptsLoading] = useState(false);
  const [attemptsError, setAttemptsError] = useState(null);

  const loadAttempts = useCallback(async () => {
    setAttemptsLoading(true);
    setAttemptsError(null);
    try {
      const list = await library.sectionTestAttempts(courseId, sid);
      setAttempts(list);
    } catch (err) {
      setAttemptsError(err.status === 404 ? "Chapter not found." : err.message || "Failed to load past attempts.");
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
          {attemptsError && <ErrorBanner error={attemptsError} />}
          {!attemptsLoading && !attemptsError && attempts !== null && attempts.length === 0 && (
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
