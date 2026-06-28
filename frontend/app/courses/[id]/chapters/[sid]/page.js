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
        setSiblings(findSiblings(courseData.chapters, sid));
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

      {/* ── Tutor chat ── */}
      <TutorChat courseId={id} sid={sid} />
    </main>
  );
}
