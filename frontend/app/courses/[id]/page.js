"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { library } from "../../lib/api";
import { Badge, ErrorBanner, Panel, ProgressBar, Spinner, StatusBadge } from "../../components/ui";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ACTIVE_GEN = new Set(["queued", "running", "retry_scheduled", "generating"]);

const IMPORTANCE_TONE = {
  core: "ok",
  essential: "ok",
  important: "info",
  supplemental: "muted",
  optional: "muted",
  advanced: "warn",
};

function importanceTone(imp) {
  if (!imp) return "muted";
  return IMPORTANCE_TONE[String(imp).toLowerCase()] || "muted";
}

function statusTone(status) {
  if (!status) return "muted";
  if (status === "ready") return "ok";
  if (status === "generating") return "warn";
  if (status === "failed") return "bad";
  return "muted";
}

// ---------------------------------------------------------------------------
// Chapter row
// ---------------------------------------------------------------------------

function ChapterRow({ chapter, courseId, index }) {
  const sid = chapter.section_id;

  return (
    <li
      style={{
        borderTop: "1px solid var(--border)",
        padding: "0",
      }}
    >
      <Link
        href={`/courses/${encodeURIComponent(courseId)}/chapters/${encodeURIComponent(sid)}`}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 14,
          padding: "14px 16px",
          textDecoration: "none",
          color: "var(--text)",
          borderRadius: 0,
          transition: "background 0.12s",
        }}
        className="toc-row"
      >
        {/* Chapter number */}
        <span
          style={{
            flexShrink: 0,
            width: 28,
            height: 28,
            border: "1px solid var(--border)",
            borderRadius: "50%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 12,
            fontWeight: 700,
            color: "var(--muted)",
            background: "#0e1422",
          }}
        >
          {index + 1}
        </span>

        {/* Title + meta */}
        <span style={{ flex: 1, minWidth: 0 }}>
          <span
            style={{
              display: "block",
              fontWeight: 500,
              fontSize: 15,
              color: "var(--text)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {chapter.title || sid}
          </span>
        </span>

        {/* Badges */}
        <span style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
          {chapter.importance && (
            <Badge tone={importanceTone(chapter.importance)}>
              {chapter.importance}
            </Badge>
          )}
          {chapter.completed && (
            <Badge tone="ok" dot>
              done
            </Badge>
          )}
          {chapter.status && chapter.status !== "ready" && (
            <Badge tone={statusTone(chapter.status)} dot>
              {chapter.status.replace(/_/g, " ")}
            </Badge>
          )}
          <span className="muted" style={{ fontSize: 13, marginLeft: 2 }}>→</span>
        </span>
      </Link>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Course-level chat panel
// ---------------------------------------------------------------------------

function CourseChatPanel({ courseId }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [chatError, setChatError] = useState(null);

  useEffect(() => {
    library.courseChatHistory(courseId)
      .then((res) => {
        const history = res.history || [];
        setMessages(
          history.map(({ role, content, citations }) => ({ role, content, citations }))
        );
      })
      .catch(() => {
        // Non-fatal: a brand-new course has no history — stay empty
      });
  }, [courseId]);

  const handleSend = useCallback(async () => {
    const question = input.trim();
    if (!question || sending) return;
    setMessages((prev) => [...prev, { role: "user", content: question, citations: null }]);
    setInput("");
    setSending(true);
    setChatError(null);
    try {
      const res = await library.courseChat(courseId, question);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: res.answer, citations: res.citations },
      ]);
    } catch (err) {
      setChatError(err.message || "Failed to get a response.");
    } finally {
      setSending(false);
    }
  }, [input, sending, courseId]);

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  return (
    <Panel title="Ask about this material">
      {/* Transcript */}
      {messages.length > 0 && (
        <div
          style={{
            marginBottom: 14,
            display: "flex",
            flexDirection: "column",
            gap: 10,
            maxHeight: 380,
            overflowY: "auto",
          }}
        >
          {messages.map((msg, i) => {
            const isUser = msg.role === "user";
            return (
              <div
                key={i}
                style={{
                  display: "flex",
                  justifyContent: isUser ? "flex-end" : "flex-start",
                }}
              >
                <div
                  style={{
                    maxWidth: "82%",
                    background: isUser
                      ? "rgba(91,140,255,0.12)"
                      : "rgba(255,255,255,0.04)",
                    border: isUser
                      ? "1px solid rgba(91,140,255,0.25)"
                      : "1px solid var(--border)",
                    borderRadius: isUser
                      ? "12px 12px 4px 12px"
                      : "12px 12px 12px 4px",
                    padding: "9px 13px",
                    fontSize: 14,
                    lineHeight: 1.55,
                    color: "var(--text)",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {msg.content}
                  {!isUser &&
                    msg.citations &&
                    msg.citations.length > 0 && (
                      <div
                        style={{
                          marginTop: 6,
                          fontSize: 12,
                          color: "var(--muted)",
                        }}
                      >
                        Sources: {msg.citations.map((c) => c.source_ref).join(", ")}
                      </div>
                    )}
                </div>
              </div>
            );
          })}
          {sending && (
            <div style={{ display: "flex", justifyContent: "flex-start" }}>
              <div
                style={{
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid var(--border)",
                  borderRadius: "12px 12px 12px 4px",
                  padding: "9px 13px",
                }}
              >
                <Spinner label="Thinking…" />
              </div>
            </div>
          )}
        </div>
      )}

      {/* Empty state hint */}
      {messages.length === 0 && !sending && (
        <p style={{ margin: "0 0 14px", fontSize: 14, color: "var(--muted)" }}>
          Ask a question about the course material and get a grounded answer with source citations.
        </p>
      )}

      {/* Chat error */}
      {chatError && <ErrorBanner error={chatError} />}

      {/* Input row */}
      <div style={{ display: "flex", gap: 8 }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask a question…"
          disabled={sending}
          style={{
            flex: 1,
            background: "rgba(255,255,255,0.05)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            padding: "9px 13px",
            fontSize: 14,
            color: "var(--text)",
            outline: "none",
          }}
        />
        <button
          onClick={handleSend}
          disabled={sending || !input.trim()}
          style={{
            flexShrink: 0,
            padding: "9px 18px",
            background:
              sending || !input.trim()
                ? "rgba(91,140,255,0.08)"
                : "rgba(91,140,255,0.18)",
            border: "1px solid rgba(91,140,255,0.30)",
            borderRadius: 8,
            color:
              sending || !input.trim()
                ? "var(--muted)"
                : "var(--accent, #5b8cff)",
            fontSize: 14,
            fontWeight: 600,
            cursor: sending || !input.trim() ? "not-allowed" : "pointer",
            transition: "background 0.12s, color 0.12s",
          }}
        >
          {sending ? "Thinking…" : "Send"}
        </button>
      </div>
    </Panel>
  );
}

// ---------------------------------------------------------------------------
// Course TOC page
// ---------------------------------------------------------------------------

export default function CoursePage() {
  const params = useParams();
  const id = decodeURIComponent(params.id);

  const [data, setData] = useState(null);   // { course, plan, chapters }
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tocSearch, setTocSearch] = useState("");
  const pollRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const result = await library.getCourse(id);
      setData(result);
      return result;
    } catch (err) {
      setError(err.message || "Failed to load course.");
      return null;
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
    return () => pollRef.current && clearInterval(pollRef.current);
  }, [load]);

  // Poll while generation is in flight
  useEffect(() => {
    const genStatus = data?.course?.generation_status || data?.course?.status;
    if (ACTIVE_GEN.has(genStatus)) {
      if (!pollRef.current) {
        pollRef.current = setInterval(async () => {
          const result = await load();
          const s = result?.course?.generation_status || result?.course?.status;
          if (!ACTIVE_GEN.has(s) && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        }, 3000);
      }
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, [data, load]);

  // ── Loading / error ─────────────────────────────────────────────────────
  if (loading) {
    return (
      <main>
        <Link href="/" className="muted" style={{ fontSize: 14 }}>← Library</Link>
        <Spinner label="Loading course…" />
      </main>
    );
  }

  if (error || !data) {
    return (
      <main>
        <Link href="/" className="muted" style={{ fontSize: 14 }}>← Library</Link>
        <ErrorBanner error={error || "Course not found."} />
      </main>
    );
  }

  const { course = {}, plan: planItems = [], chapters: rawChapters = [] } = data;
  // Sort chapters by plan order defensively (backend sorts too, but be robust)
  const orderMap = {};
  (planItems || []).forEach((item) => {
    if (item.section_id != null) orderMap[item.section_id] = item.order ?? Infinity;
  });
  const chapters = [...rawChapters].sort((a, b) => {
    const oa = orderMap[a.section_id] ?? Infinity;
    const ob = orderMap[b.section_id] ?? Infinity;
    return oa - ob;
  });

  const completedCount = chapters.filter((c) => c.completed).length;
  const readyCount = chapters.filter((c) => c.status === "ready").length;
  const isGenerating = ACTIVE_GEN.has(course.generation_status || course.status);

  const filteredChapters = tocSearch.trim()
    ? chapters.filter((c) =>
        (c.title || c.section_id || "").toLowerCase().includes(tocSearch.trim().toLowerCase())
      )
    : chapters;

  return (
    <main>
      {/* ── Back link ── */}
      <div style={{ marginBottom: 24 }}>
        <Link href="/" className="muted" style={{ fontSize: 14 }}>
          ← Library
        </Link>
      </div>

      <ErrorBanner error={error} />

      {/* ── Book cover / header ── */}
      <div style={{
        background: "var(--panel)",
        border: "1px solid var(--border)",
        borderRadius: 16,
        padding: "28px 32px",
        marginBottom: 28,
      }}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 16, flexWrap: "wrap" }}>
          {/* Book icon */}
          <div style={{
            flexShrink: 0,
            width: 56,
            height: 56,
            background: "rgba(91,140,255,0.1)",
            border: "1px solid rgba(91,140,255,0.25)",
            borderRadius: 12,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: 28,
          }}>
            📖
          </div>

          <div style={{ flex: 1, minWidth: 0 }}>
            <h1 style={{ margin: "0 0 8px", fontSize: 26, fontWeight: 800, lineHeight: 1.25 }}>
              {course.title || id}
            </h1>

            {/* Status row */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              {course.status && <StatusBadge status={course.status} />}
              {course.generation_status && course.generation_status !== course.status && (
                <StatusBadge status={course.generation_status} />
              )}
              <span className="muted" style={{ fontSize: 13 }}>
                {chapters.length} chapter{chapters.length !== 1 ? "s" : ""}
                {readyCount > 0 && readyCount < chapters.length
                  ? ` · ${readyCount} ready`
                  : ""}
              </span>
            </div>

            {/* Progress if studying */}
            {completedCount > 0 && (
              <div style={{ marginTop: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13, marginBottom: 5 }}>
                  <span className="muted">Progress</span>
                  <span className="muted">{completedCount}/{chapters.length} completed</span>
                </div>
                <ProgressBar
                  value={completedCount}
                  max={chapters.length}
                  tone="ok"
                />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Ingestion in progress banner ── */}
      {isGenerating && (
        <div style={{
          background: "rgba(210,153,34,0.08)",
          border: "1px solid rgba(210,153,34,0.35)",
          borderRadius: 10,
          padding: "12px 18px",
          marginBottom: 20,
          display: "flex",
          alignItems: "center",
          gap: 10,
          fontSize: 14,
          color: "var(--warn)",
        }}>
          <span className="spinner-dot" style={{ borderTopColor: "var(--warn)", borderColor: "rgba(210,153,34,0.3)" }} />
          Preparing course… chapters will be available to read shortly.
        </div>
      )}

      {/* ── Table of Contents ── */}
      <div style={{
        background: "var(--panel)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        overflow: "hidden",
      }}>
        {/* TOC header */}
        <div style={{
          padding: "16px 20px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Table of Contents</h2>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {readyCount > 0 && (
              <span className="muted" style={{ fontSize: 13 }}>
                {readyCount}/{chapters.length} ready to read
              </span>
            )}
            <a
              href={library.ankiTsvUrl(id)}
              download={`${id}.tsv`}
              style={{
                fontSize: 12,
                padding: "5px 11px",
                background: "rgba(91,140,255,0.10)",
                border: "1px solid rgba(91,140,255,0.28)",
                borderRadius: 6,
                color: "var(--accent, #5b8cff)",
                textDecoration: "none",
                whiteSpace: "nowrap",
                fontWeight: 500,
              }}
            >
              Export Anki deck (.tsv)
            </a>
          </div>
        </div>

        {/* TOC search */}
        {chapters.length > 0 && (
          <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--border)" }}>
            <input
              type="search"
              value={tocSearch}
              onChange={(e) => setTocSearch(e.target.value)}
              placeholder="Filter chapters…"
              style={{
                width: "100%",
                boxSizing: "border-box",
                background: "rgba(255,255,255,0.04)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                padding: "7px 12px",
                fontSize: 14,
                color: "var(--text)",
                outline: "none",
                margin: 0,
              }}
            />
          </div>
        )}

        {chapters.length === 0 ? (
          <div style={{ padding: "24px 20px" }}>
            {isGenerating ? (
              <p className="muted" style={{ margin: 0 }}>
                Chapters are being prepared — check back shortly.
              </p>
            ) : (
              <p className="muted" style={{ margin: 0 }}>
                No chapters found for this course.
              </p>
            )}
          </div>
        ) : filteredChapters.length === 0 ? (
          <div style={{ padding: "24px 20px" }}>
            <p className="muted" style={{ margin: 0 }}>No chapters match &ldquo;{tocSearch}&rdquo;.</p>
          </div>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {/* Inject hover style via global rule — keeps rows clean */}
            <style>{`
              .toc-row:hover {
                background: rgba(91,140,255,0.05);
                text-decoration: none !important;
              }
            `}</style>
            {filteredChapters.map((ch, i) => (
              <ChapterRow
                key={ch.section_id || i}
                chapter={ch}
                courseId={id}
                index={chapters.indexOf(ch)}
              />
            ))}
          </ul>
        )}
      </div>

      {/* ── Ask about this material ── */}
      <div style={{ marginTop: 24 }}>
        <CourseChatPanel courseId={id} />
      </div>

      {/* ── Footer note ── */}
      {chapters.length > 0 && (
        <p className="muted" style={{ marginTop: 16, fontSize: 13, textAlign: "center" }}>
          Click any chapter to start reading.
        </p>
      )}
    </main>
  );
}
