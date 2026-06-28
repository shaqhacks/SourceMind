"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { api, library } from "../lib/api";
import { Badge, ErrorBanner, Panel } from "../components/ui";

const SOURCE_TYPES = ["text", "markdown", "url", "youtube"];

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
          {chapters.map((ch) => (
            <div key={ch.id || ch.chapter_id || ch.title} className="row" style={{ padding: "3px 0" }}>
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

      // Fetch the plan for review
      const planData = await library.getPlan(id);
      setPlan(planData);
      setStage("reviewing");
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

          const status = data.course?.status;
          if (status === "ready" || status === "failed") {
            stopPolling();
            setStage(status);
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
    <Panel title="Upload PDFs → Review plan → Generate">
      <p className="muted">
        Upload one or more PDFs. The system builds an outline and study plan — review it, then
        approve to generate the full course.
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

          <label htmlFor="lib-files">PDF file(s)</label>
          <input
            id="lib-files"
            type="file"
            accept="application/pdf"
            multiple
            onChange={(e) => setLibFiles(e.target.files)}
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
            planItems.map((item, i) => <PlanItem key={item.id || i} item={item} />)
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
// Legacy upload panels (unchanged)
// ---------------------------------------------------------------------------

export default function Upload() {
  const [sourceType, setSourceType] = useState("text");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [subjectPdf, setSubjectPdf] = useState(null);
  const [busy, setBusy] = useState("");
  const [sourceResult, setSourceResult] = useState(null);
  const [pdfResult, setPdfResult] = useState(null);
  const [error, setError] = useState(null);

  function run(kind, fn) {
    return async (e) => {
      e.preventDefault();
      setBusy(kind);
      setError(null);
      try {
        await fn();
      } catch (err) {
        setError(err.message);
      } finally {
        setBusy("");
      }
    };
  }

  const submitSource = run("source", async () => {
    setSourceResult(null);
    const body = { source_type: sourceType, content };
    if (title.trim()) body.title = title.trim();
    setSourceResult(await api.uploadSource(body));
  });

  const submitSubjectPdf = run("subject", async () => {
    setPdfResult(null);
    const form = new FormData();
    form.append("file", subjectPdf);
    if (title.trim()) form.append("title", title.trim());
    setPdfResult({ kind: "subject", ...(await api.uploadSubjectPdf(form)) });
  });

  return (
    <main>
      <ErrorBanner error={error} />

      {/* ── New library flow ── */}
      <LibraryUploadFlow />

      <Panel title="Ingest a source">
        <p className="muted">
          Paste text, markdown, a YouTube transcript, or fetched page HTML. The backend normalizes
          it, decomposes it into a competency tree, and scores the tree.
        </p>
        <form onSubmit={submitSource}>
          <label htmlFor="title">Title (optional)</label>
          <input id="title" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Intro Algebra" />

          <label htmlFor="type">Source type</label>
          <select id="type" value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
            {SOURCE_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>

          <label htmlFor="content">Content</label>
          <textarea
            id="content"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={"Chapter 1: Foundations\n1.1 Integers\nIntegers are whole numbers..."}
          />

          <button type="submit" disabled={busy !== "" || !content.trim()}>
            {busy === "source" ? "Working…" : "Decompose & score"}
          </button>
        </form>

        {sourceResult && (
          <div className="panel" style={{ marginTop: 16 }}>
            <div className="row">
              <strong>{sourceResult.title}</strong>
              <Badge tone={sourceResult.rubric_passed ? "ok" : "bad"} dot>
                {sourceResult.rubric_passed ? "PASS" : "FAIL"} · score{" "}
                {Number(sourceResult.rubric_total).toFixed(2)}
              </Badge>
            </div>
            <p className="muted" style={{ marginBottom: 0 }}>
              {sourceResult.chapters_count} chapters · {sourceResult.competencies_count} competencies ·{" "}
              {sourceResult.source_type}
            </p>
          </div>
        )}
      </Panel>

      <Panel title="Upload a subject PDF (legacy)">
        <form onSubmit={submitSubjectPdf}>
          <label htmlFor="subjpdf">PDF file</label>
          <input
            id="subjpdf"
            type="file"
            accept="application/pdf"
            onChange={(e) => setSubjectPdf(e.target.files ? e.target.files[0] : null)}
          />
          <button type="submit" disabled={busy !== "" || !subjectPdf}>
            {busy === "subject" ? "Uploading…" : "Create subject"}
          </button>
        </form>
      </Panel>

      {pdfResult && pdfResult.kind === "subject" && (
        <Panel title="Created">
          <p style={{ margin: 0 }}>
            Subject <strong>{pdfResult.subject_id}</strong> · {pdfResult.competencies_count}{" "}
            competencies · {pdfResult.quotes_count} quotes · {pdfResult.status}
          </p>
        </Panel>
      )}
    </main>
  );
}
