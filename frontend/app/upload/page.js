"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { library } from "../lib/api";
import { Badge, ErrorBanner, Panel } from "../components/ui";

// ---------------------------------------------------------------------------
// Library upload flow: upload → ingest → ready (ingest now finishes fast;
// no plan-review / approve-generate gate anymore).
// ---------------------------------------------------------------------------

function LibraryUploadFlow() {
  const router = useRouter();
  const [stage, setStage] = useState("idle"); // idle|uploading|ingesting|ready
  const [libTitle, setLibTitle] = useState("");
  const [libFiles, setLibFiles] = useState(null);
  const [courseId, setCourseId] = useState(null);
  const [courseData, setCourseData] = useState(null);
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

  /** Poll getCourse until status==="ready" or "ingest_failed". */
  function startReadyPolling(id) {
    stopPolling();
    intervalRef.current = setInterval(async () => {
      try {
        const data = await library.getCourse(id);
        setCourseData(data);
        const s = data.course?.status;
        if (s === "ready") {
          stopPolling();
          setStage("ready");
          // Auto-redirect after a short pause so the user sees the success state
          setTimeout(() => router.push(`/courses/${encodeURIComponent(id)}`), 1200);
        } else if (s === "ingest_failed") {
          stopPolling();
          setLibError(data.course?.generation_last_error || "Ingestion failed.");
          setStage("idle");
        }
      } catch {
        // transient network error — keep polling
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

      setStage("ingesting");
      startReadyPolling(id);
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
      startReadyPolling(id);
    } catch (err) {
      setLibError(err.message);
      setStage("idle");
    }
  }

  return (
    <Panel title="Upload & Build Course">
      <p className="muted">
        Upload one or more files (PDF, Word, PowerPoint, text, or Markdown) or add a URL, pasted
        text, or YouTube link. Chapters are available to read immediately after ingestion.
      </p>

      {libError && <ErrorBanner error={libError} />}

      {/* ── Stage: idle / uploading — file upload form ── */}
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
            {stage === "uploading" ? "Uploading…" : "Upload & Build Course"}
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

      {/* ── Stage: ingesting (reading + splitting into chapters) ── */}
      {stage === "ingesting" && (
        <div className="panel">
          <div className="row" style={{ marginBottom: 6 }}>
            <span>Reading and splitting into chapters…</span>
            <Badge tone="ok">{courseData?.course?.status || "ingesting"}</Badge>
          </div>
          <p className="muted" style={{ margin: 0, fontSize: 13 }}>
            This usually takes a few seconds. You&apos;ll be taken to the course automatically when ready.
          </p>
        </div>
      )}

      {/* ── Stage: ready ── */}
      {stage === "ready" && (
        <div className="panel" style={{ marginTop: 8 }}>
          <div className="row">
            <span>
              ✓ Course <strong>{courseData?.course?.title || courseId}</strong> is ready.
            </span>
            <Link href={`/courses/${encodeURIComponent(courseId)}`}>Open course →</Link>
          </div>
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
