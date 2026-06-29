"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { library } from "../lib/api";
import { Badge, ErrorBanner, Panel } from "../components/ui";

// ---------------------------------------------------------------------------
// Library upload flow: upload → plan review → approve + generate → poll
// ---------------------------------------------------------------------------

const IMPORTANCE_TONE = { critical: "bad", high: "warn", medium: "ok", low: "muted" };

function PlanItem({ item }) {
  return (
    <div className="panel" style={{ marginBottom: 12 }}>
      <div className="row" style={{ marginBottom: 6 }}>
        <strong>{item.title}</strong>
        <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {item.target_words != null && (
            <span className="muted" style={{ fontSize: 13 }}>
              ~{item.target_words} words
            </span>
          )}
          {item.importance && (
            <Badge tone={IMPORTANCE_TONE[item.importance] || "ok"}>{item.importance}</Badge>
          )}
        </span>
      </div>
      {item.objectives && item.objectives.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {item.objectives.map((obj, i) => (
            <li key={i} className="muted" style={{ fontSize: 13 }}>
              {obj}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function GenerationProgress({ course, chapters }) {
  const prog = course.generation_progress || {};
  const completed = prog.completed ?? 0;
  const total = prog.total ?? 0;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

  return (
    <div>
      <div className="row" style={{ marginBottom: 8 }}>
        <span>
          Generating… <strong>{completed}/{total}</strong> chapters
        </span>
        <Badge tone={course.status === "failed" ? "bad" : "ok"}>{course.status}</Badge>
      </div>
      <div
        style={{
          height: 6,
          background: "var(--border, #333)",
          borderRadius: 3,
          overflow: "hidden",
          marginBottom: 12,
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            background: "var(--accent, #7c3aed)",
            transition: "width 0.4s ease",
          }}
        />
      </div>
      {chapters && chapters.length > 0 && (
        <div style={{ fontSize: 13 }}>
          {chapters.map((ch, i) => (
            <div key={ch.section_id || i} className="row" style={{ padding: "3px 0" }}>
              <span className="muted">{ch.title}</span>
              <Badge tone={ch.status === "ready" ? "ok" : ch.status === "failed" ? "bad" : "muted"}>
                {ch.status || "pending"}
              </Badge>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function LibraryUploadFlow() {
  const [stage, setStage] = useState("idle"); // idle|uploading|reviewing|approving|generating|ready|failed
  const [libTitle, setLibTitle] = useState("");
  const [libFiles, setLibFiles] = useState(null);
  const [courseId, setCourseId] = useState(null);
  const [plan, setPlan] = useState(null);
  const [courseData, setCourseData] = useState(null); // { course, chapters }
  const [libError, setLibError] = useState(null);
  const [sourceKind, setSourceKind] = useState("url");
  const [sourceValue, setSourceValue] = useState("");
  const [sourceTitle, setSourceTitle] = useState("");
  const intervalRef = useRef(null);

  // Clear polling on unmount
  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  function stopPolling() {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }

  function startIngestPolling(id) {
    stopPolling();
    intervalRef.current = setInterval(async () => {
      try {
        const data = await library.getCourse(id);
        setCourseData(data);
        const s = data.course?.status;
        if (s === "needs_review") {
          stopPolling();
          const planData = await library.getPlan(id);
          setPlan(planData);
          setStage("reviewing");
        } else if (s === "ingest_failed") {
          stopPolling();
          setLibError(data.course?.generation_last_error || "Ingestion failed.");
          setStage("idle");
        }
      } catch (pollErr) {
        // transient error — keep polling
      }
    }, 1500);
  }

  async function handleUpload(e) {
    e.preventDefault();
    setLibError(null);
    setStage("uploading");

    try {
      const form = new FormData();
      if (libTitle.trim()) form.append("title", libTitle.trim());
      Array.from(libFiles || []).forEach((f) => form.append("files", f));

      const result = await library.uploadPdfs(form);
      const id = result.course_id;
      setCourseId(id);

      // Ingest (extract → outline → plan) runs in the background. Poll the
      // course status and show progress until the plan is ready for review.
      setStage("ingesting");
      startIngestPolling(id);
    } catch (err) {
      setLibError(err.message);
      setStage("idle");
    }
  }

  async function handleSource(e) {
    e.preventDefault();
    if (!sourceValue.trim()) {
      setLibError("Please enter a value.");
      return;
    }
    setLibError(null);
    setStage("uploading");

    try {
      const result = await library.uploadSource({
        kind: sourceKind,
        value: sourceValue.trim(),
        title: sourceTitle.trim(),
      });
      const id = result.course_id;
      setCourseId(id);

      setStage("ingesting");
      startIngestPolling(id);
    } catch (err) {
      setLibError(err.message);
      setStage("idle");
    }
  }

  async function handleApproveAndGenerate() {
    setLibError(null);
    setStage("approving");

    try {
      await library.approvePlan(courseId);
      await library.generate(courseId);
      setStage("generating");

      // Start polling
      intervalRef.current = setInterval(async () => {
        try {
          const data = await library.getCourse(courseId);
          setCourseData(data);

          const s = data.course?.generation_status || data.course?.status;
          if (s === "ready" || s === "failed") {
            stopPolling();
            setStage(s);
          }
        } catch (pollErr) {
          // Don't stop on transient poll errors
        }
      }, 2000);
    } catch (err) {
      setLibError(err.message);
      setStage("reviewing"); // fall back so user can retry
    }
  }

  const planItems =
    plan?.plan_items || plan?.items || plan?.chapters || (Array.isArray(plan) ? plan : null);

  return (
    <Panel title="Upload files → Review plan → Generate">
      <p className="muted">
        Upload one or more files (PDF, Word, PowerPoint, text, or Markdown) or add a URL, pasted
        text, or YouTube link. The system builds an outline and study plan — review it, then approve
        to generate the full course.
      </p>

      {libError && <ErrorBanner error={libError} />}

      {/* ── Stage: idle / uploading ── */}
      {(stage === "idle" || stage === "uploading") && (
        <form onSubmit={handleUpload}>
          <label htmlFor="lib-title">Course title (optional)</label>
          <input
            id="lib-title"
            value={libTitle}
            onChange={(e) => setLibTitle(e.target.value)}
            placeholder="e.g. Introduction to Calculus"
            disabled={stage === "uploading"}
          />

          <label htmlFor="lib-files">PDF, Word, PowerPoint, text, or Markdown</label>
          <input
            id="lib-files"
            type="file"
            accept=".pdf,.docx,.pptx,.txt,.md"
            multiple
            onChange={(e) => {
              const fs = e.target.files;
              setLibFiles(fs);
              // Auto-fill the title from the first filename when empty (editable).
              if (fs && fs.length > 0 && !libTitle.trim()) {
                const stem = fs[0].name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
                if (stem) setLibTitle(stem);
              }
            }}
            disabled={stage === "uploading"}
          />

          <button
            type="submit"
            disabled={stage === "uploading" || !libFiles || libFiles.length === 0}
          >
            {stage === "uploading" ? "Uploading & building plan…" : "Upload & Build Plan"}
          </button>
        </form>
      )}

      {/* ── Stage: idle / uploading — source form ── */}
      {(stage === "idle" || stage === "uploading") && (
        <div className="panel" style={{ marginTop: 16 }}>
          <strong>Or add from URL, text, or YouTube</strong>
          <form onSubmit={handleSource} style={{ marginTop: 12 }}>
            <label htmlFor="source-kind">Type</label>
            <select
              id="source-kind"
              value={sourceKind}
              onChange={(e) => setSourceKind(e.target.value)}
              disabled={stage === "uploading"}
            >
              <option value="url">URL</option>
              <option value="text">Paste text</option>
              <option value="youtube">YouTube</option>
            </select>

            <label htmlFor="source-value">
              {sourceKind === "text" ? "Text content" : sourceKind === "youtube" ? "YouTube URL" : "URL"}
            </label>
            <textarea
              id="source-value"
              value={sourceValue}
              onChange={(e) => setSourceValue(e.target.value)}
              placeholder={
                sourceKind === "text"
                  ? "Paste your text here…"
                  : sourceKind === "youtube"
                  ? "https://www.youtube.com/watch?v=…"
                  : "https://…"
              }
              rows={sourceKind === "text" ? 5 : 2}
              disabled={stage === "uploading"}
              style={{ width: "100%", boxSizing: "border-box" }}
            />

            <label htmlFor="source-title">Course title (optional)</label>
            <input
              id="source-title"
              value={sourceTitle}
              onChange={(e) => setSourceTitle(e.target.value)}
              placeholder="e.g. Introduction to Calculus"
              disabled={stage === "uploading"}
            />

            <button type="submit" disabled={stage === "uploading"}>
              {stage === "uploading" ? "Processing…" : "Add source"}
            </button>
          </form>
        </div>
      )}

      {/* ── Stage: ingesting (outline + plan building in background) ── */}
      {stage === "ingesting" && (
        <div className="panel">
          <div className="row" style={{ marginBottom: 6 }}>
            <span>Reading your material and detecting chapters…</span>
            <Badge tone="ok">{courseData?.course?.status || "ingesting"}</Badge>
          </div>
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>
            Building the outline and study plan. This runs in the background — it
            stays here until the plan is ready to review.
          </p>
        </div>
      )}

      {/* ── Stage: reviewing ── */}
      {stage === "reviewing" && plan && (
        <div>
          <div className="row" style={{ marginBottom: 12 }}>
            <strong style={{ fontSize: 15 }}>Study Plan</strong>
            <span className="muted" style={{ fontSize: 13 }}>
              {planItems?.length ?? 0} items
            </span>
          </div>

          {planItems && planItems.length > 0 ? (
            planItems.map((item, i) => <PlanItem key={item.section_id || i} item={item} />)
          ) : (
            <pre className="muted" style={{ fontSize: 12, overflow: "auto" }}>
              {JSON.stringify(plan, null, 2)}
            </pre>
          )}

          <div style={{ marginTop: 16, display: "flex", gap: 12, alignItems: "center" }}>
            <button onClick={handleApproveAndGenerate}>Approve &amp; Generate</button>
            <button
              style={{ background: "none", border: "1px solid var(--border,#333)", color: "inherit" }}
              onClick={() => {
                setStage("idle");
                setPlan(null);
                setCourseId(null);
              }}
            >
              Start over
            </button>
          </div>
        </div>
      )}

      {/* ── Stage: approving (brief) ── */}
      {stage === "approving" && (
        <p className="muted">Approving plan and starting generation…</p>
      )}

      {/* ── Stage: generating ── */}
      {stage === "generating" && courseData && (
        <GenerationProgress
          course={courseData.course || {}}
          chapters={courseData.chapters || []}
        />
      )}
      {stage === "generating" && !courseData && (
        <p className="muted">Generation started, waiting for first update…</p>
      )}

      {/* ── Stage: ready ── */}
      {stage === "ready" && (
        <div className="panel" style={{ marginTop: 8 }}>
          <div className="row">
            <span>
              Course <strong>{courseData?.course?.title || courseId}</strong> is ready.
            </span>
            <Link href={`/courses/${encodeURIComponent(courseId)}`}>Open course →</Link>
          </div>
        </div>
      )}

      {/* ── Stage: failed ── */}
      {stage === "failed" && (
        <div>
          <p style={{ color: "var(--red, #f87171)" }}>
            Generation failed. Check the course for details.
          </p>
          {courseId && (
            <Link href={`/courses/${encodeURIComponent(courseId)}`}>View course →</Link>
          )}
        </div>
      )}
    </Panel>
  );
}

// ---------------------------------------------------------------------------

export default function Upload() {
  return (
    <main>
      <LibraryUploadFlow />
    </main>
  );
}
