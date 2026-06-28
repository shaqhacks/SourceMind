"use client";

import { useState } from "react";

/**
 * Quiz — inline multiple-choice widget rendered by Markdown.js when it
 * encounters a ```quiz fenced code block in chapter body_md.
 *
 * Props
 *   items: Array<{ q: string, options: string[], answer: number, explain?: string }>
 *          `answer` is the 0-based index of the correct option.
 */
export default function Quiz({ items = [] }) {
  const [selected, setSelected] = useState({});   // { [qi]: oi }
  const [checked, setChecked] = useState(false);

  function pick(qi, oi) {
    if (checked) return;
    setSelected((prev) => ({ ...prev, [qi]: oi }));
  }

  function reset() {
    setSelected({});
    setChecked(false);
  }

  const answered = Object.keys(selected).length;
  const score = checked
    ? items.filter((item, qi) => selected[qi] === item.answer).length
    : null;

  if (!items.length) return null;

  return (
    <div style={{
      background: "var(--panel)",
      border: "1px solid var(--border)",
      borderRadius: 12,
      padding: "20px 24px",
      margin: "2em 0",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20 }}>
        <span style={{
          fontSize: 12,
          fontWeight: 700,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          color: "var(--accent)",
          background: "rgba(91,140,255,0.1)",
          border: "1px solid rgba(91,140,255,0.3)",
          borderRadius: 6,
          padding: "2px 10px",
        }}>
          Quiz
        </span>
        <span className="muted" style={{ fontSize: 13 }}>{items.length} question{items.length !== 1 ? "s" : ""}</span>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 28 }}>
        {items.map((item, qi) => (
          <div key={qi}>
            <p style={{ margin: "0 0 12px", fontWeight: 600, lineHeight: 1.5 }}>
              <span style={{ color: "var(--muted)", marginRight: 8 }}>{qi + 1}.</span>
              {item.q}
            </p>

            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {(item.options || []).map((opt, oi) => {
                const isCorrect = oi === item.answer;
                const isChosen = selected[qi] === oi;

                let bg = "transparent";
                let border = "1px solid var(--border)";
                let color = "var(--text)";
                let cursor = "pointer";

                if (checked) {
                  cursor = "default";
                  if (isCorrect) {
                    bg = "rgba(63,185,80,0.12)";
                    border = "1px solid rgba(63,185,80,0.5)";
                    color = "var(--ok)";
                  } else if (isChosen) {
                    bg = "rgba(248,81,73,0.1)";
                    border = "1px solid rgba(248,81,73,0.45)";
                    color = "var(--bad)";
                  }
                } else if (isChosen) {
                  bg = "rgba(91,140,255,0.1)";
                  border = "1px solid rgba(91,140,255,0.5)";
                }

                return (
                  <button
                    key={oi}
                    onClick={() => pick(qi, oi)}
                    style={{
                      margin: 0,
                      background: bg,
                      border,
                      color,
                      borderRadius: 8,
                      padding: "9px 14px",
                      textAlign: "left",
                      cursor,
                      fontWeight: isChosen ? 600 : 400,
                      fontSize: 15,
                      transition: "background 0.15s, border-color 0.15s",
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                    }}
                  >
                    <span style={{
                      flexShrink: 0,
                      width: 22,
                      height: 22,
                      border: checked
                        ? (isCorrect ? "2px solid var(--ok)" : isChosen ? "2px solid var(--bad)" : "1px solid var(--border)")
                        : (isChosen ? "2px solid var(--accent)" : "1px solid var(--border)"),
                      borderRadius: "50%",
                      background: checked
                        ? (isCorrect ? "rgba(63,185,80,0.2)" : isChosen ? "rgba(248,81,73,0.15)" : "transparent")
                        : (isChosen ? "rgba(91,140,255,0.2)" : "transparent"),
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 12,
                      color: checked ? (isCorrect ? "var(--ok)" : isChosen ? "var(--bad)" : "var(--muted)") : (isChosen ? "var(--accent)" : "var(--muted)"),
                      fontWeight: 700,
                    }}>
                      {checked && isCorrect ? "✓" : checked && isChosen ? "✗" : String.fromCharCode(65 + oi)}
                    </span>
                    {opt}
                  </button>
                );
              })}
            </div>

            {checked && item.explain && (
              <div style={{
                marginTop: 10,
                padding: "8px 12px",
                background: "rgba(91,140,255,0.06)",
                border: "1px solid rgba(91,140,255,0.2)",
                borderRadius: 7,
                fontSize: 14,
                color: "var(--muted)",
                lineHeight: 1.6,
              }}>
                <span style={{ color: "var(--accent)", fontWeight: 600, marginRight: 6 }}>Explanation:</span>
                {item.explain}
              </div>
            )}
          </div>
        ))}
      </div>

      <div style={{ marginTop: 24, display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
        {!checked ? (
          <>
            <button
              onClick={() => setChecked(true)}
              disabled={answered < items.length}
              style={{ margin: 0 }}
            >
              Check answers
            </button>
            {answered < items.length && (
              <span className="muted" style={{ fontSize: 13 }}>
                {answered}/{items.length} answered
              </span>
            )}
          </>
        ) : (
          <>
            <span style={{
              fontWeight: 700,
              fontSize: 16,
              color: score === items.length ? "var(--ok)" : score >= items.length / 2 ? "var(--warn)" : "var(--bad)",
            }}>
              {score}/{items.length} correct
              {score === items.length ? " — Perfect!" : score >= items.length / 2 ? " — Good job" : " — Keep studying"}
            </span>
            <button
              className="btn-secondary"
              onClick={reset}
              style={{ margin: 0 }}
            >
              Try again
            </button>
          </>
        )}
      </div>
    </div>
  );
}
