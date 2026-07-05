"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ErrorBanner, Panel, Spinner } from "./ui";

// ---------------------------------------------------------------------------
// Style constants — "card" variant (chapter-level Tutor Chat look)
// ---------------------------------------------------------------------------

const cardContainerStyle = {
  background: "var(--panel)",
  border: "1px solid var(--border)",
  borderRadius: 12,
  overflow: "hidden",
  display: "flex",
  flexDirection: "column",
  maxHeight: 520,
};

const cardHeaderStyle = {
  padding: "14px 18px",
  borderBottom: "1px solid var(--border)",
  display: "flex",
  alignItems: "center",
  gap: 10,
};

const cardTitleStyle = { margin: 0, fontSize: 15, fontWeight: 700 };

const cardMessagesStyle = {
  flex: 1,
  overflowY: "auto",
  padding: "14px 16px",
  display: "flex",
  flexDirection: "column",
  gap: 10,
  minHeight: 120,
};

const cardEmptyStyle = { margin: 0, fontSize: 14, fontStyle: "italic" };

const cardThinkingStyle = {
  alignSelf: "flex-start",
  color: "var(--muted)",
  fontSize: 13,
  fontStyle: "italic",
  padding: "4px 0",
};

const cardFormStyle = {
  display: "grid",
  gridTemplateColumns: "1fr auto",
  gap: 8,
  padding: "12px 14px",
  borderTop: "1px solid var(--border)",
};

function cardBubbleStyle(role) {
  const isUser = role === "user";
  return {
    alignSelf: isUser ? "flex-end" : "flex-start",
    maxWidth: "90%",
    background: isUser ? "rgba(91,140,255,0.14)" : "#0e1422",
    border: isUser ? "1px solid rgba(91,140,255,0.35)" : "1px solid var(--border)",
    borderRadius: 10,
    padding: "9px 13px",
    fontSize: 14,
    lineHeight: 1.6,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  };
}

// ---------------------------------------------------------------------------
// Style constants — "panel" variant (course-level "Ask about this material")
// ---------------------------------------------------------------------------

const panelTranscriptStyle = {
  marginBottom: 14,
  display: "flex",
  flexDirection: "column",
  gap: 10,
  maxHeight: 380,
  overflowY: "auto",
};

const panelHintStyle = { margin: "0 0 14px", fontSize: 14, color: "var(--muted)" };

const panelCitationsStyle = { marginTop: 6, fontSize: 12, color: "var(--muted)" };

const panelPendingBubbleStyle = {
  background: "rgba(255,255,255,0.04)",
  border: "1px solid var(--border)",
  borderRadius: "12px 12px 12px 4px",
  padding: "9px 13px",
};

const panelInputStyle = {
  flex: 1,
  background: "rgba(255,255,255,0.05)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  padding: "9px 13px",
  fontSize: 14,
  color: "var(--text)",
  outline: "none",
};

function panelBubbleWrapStyle(isUser) {
  return { display: "flex", justifyContent: isUser ? "flex-end" : "flex-start" };
}

function panelBubbleStyle(isUser) {
  return {
    maxWidth: "82%",
    background: isUser ? "rgba(91,140,255,0.12)" : "rgba(255,255,255,0.04)",
    border: isUser ? "1px solid rgba(91,140,255,0.25)" : "1px solid var(--border)",
    borderRadius: isUser ? "12px 12px 4px 12px" : "12px 12px 12px 4px",
    padding: "9px 13px",
    fontSize: 14,
    lineHeight: 1.55,
    color: "var(--text)",
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  };
}

function panelSendButtonStyle(disabled) {
  return {
    flexShrink: 0,
    padding: "9px 18px",
    background: disabled ? "rgba(91,140,255,0.08)" : "rgba(91,140,255,0.18)",
    border: "1px solid rgba(91,140,255,0.30)",
    borderRadius: 8,
    color: disabled ? "var(--muted)" : "var(--accent, #5b8cff)",
    fontSize: 14,
    fontWeight: 600,
    cursor: disabled ? "not-allowed" : "pointer",
    transition: "background 0.12s, color 0.12s",
  };
}

// ---------------------------------------------------------------------------
// Chat — shared Q&A widget
// ---------------------------------------------------------------------------

/**
 * Chat — shared chat widget backing both the per-chapter Tutor Chat and the
 * course-level "Ask about this material" panel. The two call sites keep their
 * own container chrome and bubble styling (selected via `variant`); the
 * message-list/input/send/history logic lives here once.
 *
 * Props
 *   sendFn(question): Promise<{answer, citations?}>  — required
 *   loadHistory?(): Promise<{history: [{role, content, citations}]}>
 *   showCitations?: boolean
 *   title?: string
 *   subtitle?: string — hint shown when the transcript is empty (panel) or a
 *     small caption next to the title (card)
 *   placeholder?: string
 *   icon?: string — emoji shown next to the title in the "card" variant
 *   variant?: "card" | "panel"  default "card"
 */
export default function Chat({
  sendFn,
  loadHistory,
  showCitations = false,
  title = "Chat",
  subtitle,
  placeholder = "Ask a question…",
  icon,
  variant = "card",
}) {
  const [messages, setMessages] = useState([]); // [{role: "user"|"assistant", content, citations}]
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const listRef = useRef(null);

  useEffect(() => {
    if (!loadHistory) return;
    loadHistory()
      .then((res) => {
        const history = res?.history || [];
        setMessages(history.map(({ role, content, citations }) => ({ role, content, citations })));
      })
      .catch((err) => {
        setError(err.status === 404 ? "Course not found." : err.message || "Failed to load chat history.");
      });
  }, [loadHistory]);

  // Keep the latest message visible by scrolling the chat's own message list.
  // Never use scrollIntoView here: it scrolls the document too, which yanked
  // the whole chapter page down to the chat on initial history load.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const send = useCallback(
    async (e) => {
      e?.preventDefault();
      const q = input.trim();
      if (!q || busy) return;
      setInput("");
      setBusy(true);
      setError(null);
      setMessages((prev) => [...prev, { role: "user", content: q, citations: null }]);
      try {
        const res = await sendFn(q);
        setMessages((prev) => [...prev, { role: "assistant", content: res.answer, citations: res.citations }]);
      } catch (err) {
        if (variant === "card") {
          setMessages((prev) => [...prev, { role: "assistant", content: `Error: ${err.message}` }]);
        } else {
          setError(err.message || "Failed to get a response.");
        }
      } finally {
        setBusy(false);
      }
    },
    [input, busy, sendFn, variant]
  );

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    },
    [send]
  );

  // ── "panel" variant: course-level chat, wrapped in the shared Panel ──────
  if (variant === "panel") {
    return (
      <Panel title={title}>
        {messages.length > 0 && (
          <div ref={listRef} style={panelTranscriptStyle}>
            {messages.map((m, i) => {
              const isUser = m.role === "user";
              return (
                <div key={i} style={panelBubbleWrapStyle(isUser)}>
                  <div style={panelBubbleStyle(isUser)}>
                    {m.content}
                    {!isUser && showCitations && m.citations && m.citations.length > 0 && (
                      <div style={panelCitationsStyle}>
                        Sources: {m.citations.map((c) => c.source_ref).join(", ")}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
            {busy && (
              <div style={{ display: "flex", justifyContent: "flex-start" }}>
                <div style={panelPendingBubbleStyle}>
                  <Spinner label="Thinking…" />
                </div>
              </div>
            )}
          </div>
        )}

        {messages.length === 0 && !busy && subtitle && <p style={panelHintStyle}>{subtitle}</p>}

        {error && <ErrorBanner error={error} />}

        <div style={{ display: "flex", gap: 8 }}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            disabled={busy}
            style={panelInputStyle}
          />
          <button
            onClick={send}
            disabled={busy || !input.trim()}
            style={panelSendButtonStyle(busy || !input.trim())}
          >
            {busy ? "Thinking…" : "Send"}
          </button>
        </div>
      </Panel>
    );
  }

  // ── "card" variant: chapter-level Tutor Chat, own bordered container ────
  return (
    <div style={cardContainerStyle}>
      <div style={cardHeaderStyle}>
        {icon && <span style={{ fontSize: 18 }}>{icon}</span>}
        <h3 style={cardTitleStyle}>{title}</h3>
        {subtitle && <span className="muted" style={{ fontSize: 13 }}>{subtitle}</span>}
      </div>

      <div ref={listRef} style={cardMessagesStyle}>
        {messages.length === 0 && (
          <p className="muted" style={cardEmptyStyle}>
            No messages yet. Ask a question below.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} style={cardBubbleStyle(m.role)}>
            {m.content}
          </div>
        ))}
        {busy && <div style={cardThinkingStyle}>Thinking…</div>}
      </div>

      {error && (
        <div style={{ padding: "0 14px" }}>
          <ErrorBanner error={error} />
        </div>
      )}

      <form onSubmit={send} style={cardFormStyle}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={placeholder}
          disabled={busy}
          style={{ margin: 0 }}
          onKeyDown={handleKeyDown}
        />
        <button type="submit" disabled={busy || !input.trim()} style={{ margin: 0, padding: "10px 18px" }}>
          Send
        </button>
      </form>
    </div>
  );
}
