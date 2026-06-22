"use client";

import { useState } from "react";
import Link from "next/link";
import { api } from "../lib/api";
import { Badge, ErrorBanner, Panel } from "../components/ui";

const SOURCE_TYPES = ["text", "markdown", "url", "youtube"];

export default function Upload() {
  const [sourceType, setSourceType] = useState("text");
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [coursePdfs, setCoursePdfs] = useState(null);
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

  const submitCoursePdf = run("course", async () => {
    setPdfResult(null);
    const form = new FormData();
    Array.from(coursePdfs || []).forEach((f) => form.append("files", f));
    if (title.trim()) form.append("title", title.trim());
    setPdfResult({ kind: "course", ...(await api.uploadCoursePdfs(form)) });
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

      <Panel title="Ingest a source">
        <p className="muted">
          Paste text, markdown, a YouTube transcript, or fetched page HTML. The backend normalizes it,
          decomposes it into a competency tree, and scores the tree.
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
                {sourceResult.rubric_passed ? "PASS" : "FAIL"} · score {Number(sourceResult.rubric_total).toFixed(2)}
              </Badge>
            </div>
            <p className="muted" style={{ marginBottom: 0 }}>
              {sourceResult.chapters_count} chapters · {sourceResult.competencies_count} competencies ·{" "}
              {sourceResult.source_type}
            </p>
          </div>
        )}
      </Panel>

      <Panel title="Upload course PDFs">
        <p className="muted">Creates a draft course (outline → generate book).</p>
        <form onSubmit={submitCoursePdf}>
          <label htmlFor="coursepdf">PDF file(s)</label>
          <input
            id="coursepdf"
            type="file"
            accept="application/pdf"
            multiple
            onChange={(e) => setCoursePdfs(e.target.files)}
          />
          <button type="submit" disabled={busy !== "" || !coursePdfs || coursePdfs.length === 0}>
            {busy === "course" ? "Uploading…" : "Create course"}
          </button>
        </form>
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

      {pdfResult && (
        <Panel title="Created">
          {pdfResult.kind === "course" ? (
            <div className="row">
              <span>
                Course <strong>{pdfResult.title || pdfResult.course_id}</strong> · {pdfResult.chapters_count} chapters ·{" "}
                {pdfResult.sections_count} sections
              </span>
              <Link href={`/courses/${encodeURIComponent(pdfResult.course_id)}`}>Open outline →</Link>
            </div>
          ) : (
            <p style={{ margin: 0 }}>
              Subject <strong>{pdfResult.subject_id}</strong> · {pdfResult.competencies_count} competencies ·{" "}
              {pdfResult.quotes_count} quotes · {pdfResult.status}
            </p>
          )}
        </Panel>
      )}
    </main>
  );
}
