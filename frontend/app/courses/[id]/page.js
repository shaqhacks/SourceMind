"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { api } from "../../lib/api";
import { Badge, ErrorBanner, Panel, ProgressBar, Spinner, StatusBadge } from "../../components/ui";

const ACTIVE_GEN = new Set(["queued", "running", "retry_scheduled"]);

// Per-section generation state for the outline indicator.
function sectionState(section) {
  if (section.status === "ready") return { tone: "ok", label: "ready" };
  if (section.status === "needs_review") return { tone: "warn", label: "review" };
  if (section.status === "generating") return { tone: "warn", label: "generating" };
  return { tone: "muted", label: "pending" };
}

export default function CoursePage() {
  const params = useParams();
  const router = useRouter();
  const id = decodeURIComponent(params.id);

  const [course, setCourse] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [courseActionBusy, setCourseActionBusy] = useState(false);
  const pollRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const doc = await api.getCourse(id);
      setCourse(doc);
      return doc;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
    return () => pollRef.current && clearInterval(pollRef.current);
  }, [load]);

  // Poll while generation is in flight.
  useEffect(() => {
    const status = course && course.generation && course.generation.status;
    if (ACTIVE_GEN.has(status)) {
      if (!pollRef.current) {
        pollRef.current = setInterval(async () => {
          const doc = await load();
          const s = doc && doc.generation && doc.generation.status;
          if (!ACTIVE_GEN.has(s) && pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        }, 2500);
      }
    } else if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, [course, load]);

  function editChapter(ci, field, value) {
    setCourse((prev) => {
      const next = structuredClone(prev);
      next.chapters[ci][field] = value;
      return next;
    });
  }
  function editSection(ci, si, field, value) {
    setCourse((prev) => {
      const next = structuredClone(prev);
      next.chapters[ci].sections[si][field] = value;
      return next;
    });
  }

  async function saveOutline() {
    setSaving(true);
    setError(null);
    try {
      const updated = await api.putOutline(id, course.chapters);
      setCourse(updated);
      setSavedAt(new Date().toLocaleTimeString());
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function generate() {
    setGenerating(true);
    setError(null);
    try {
      const updated = await api.generateCourse(id);
      setCourse(updated);
    } catch (err) {
      setError(err.message);
    } finally {
      setGenerating(false);
    }
  }

  async function regenerate(sid) {
    setError(null);
    try {
      setCourse(await api.regenerateSection(id, sid));
    } catch (err) {
      setError(err.message);
    }
  }

  async function archiveToggle() {
    setCourseActionBusy(true);
    setError(null);
    try {
      const updated = course.archived_at ? await api.restoreCourse(id) : await api.archiveCourse(id);
      setCourse(updated);
    } catch (err) {
      setError(err.message);
    } finally {
      setCourseActionBusy(false);
    }
  }

  async function deleteCourse() {
    if (!window.confirm(`Delete "${course.title || id}" permanently?`)) return;
    setCourseActionBusy(true);
    setError(null);
    try {
      await api.deleteCourse(id);
      router.push("/");
    } catch (err) {
      setError(err.message);
      setCourseActionBusy(false);
    }
  }

  if (loading) return <Spinner label="Loading course…" />;
  if (!course) return <ErrorBanner error={error || "Course not found."} />;

  const gen = course.generation || {};
  const chapters = course.chapters || [];

  return (
    <main>
      <div className="row" style={{ marginBottom: 16 }}>
        <div>
          <Link href="/" className="muted">
            ← Dashboard
          </Link>
          <h2 style={{ margin: "6px 0 0" }}>{course.title || id}</h2>
        </div>
        <span className="row" style={{ gap: 8 }}>
          {course.archived_at && <Badge tone="muted">archived</Badge>}
          <StatusBadge status={course.status} />
        </span>
      </div>

      <ErrorBanner error={error} />

      <Panel
        title="Course actions"
        action={
          <span className="row" style={{ gap: 8 }}>
            <button className="btn-secondary" type="button" onClick={archiveToggle} disabled={courseActionBusy}>
              {course.archived_at ? "Restore" : "Archive"}
            </button>
            <button className="btn-danger" type="button" onClick={deleteCourse} disabled={courseActionBusy}>
              Delete
            </button>
          </span>
        }
      >
        {course.archived_at ? (
          <p className="muted" style={{ margin: 0 }}>Archived {course.archived_at}</p>
        ) : (
          <p className="muted" style={{ margin: 0 }}>Visible on the dashboard and included in review reminders.</p>
        )}
      </Panel>

      <Panel
        title="Generation"
        action={
          <button onClick={generate} disabled={generating || ACTIVE_GEN.has(gen.status)}>
            {generating || ACTIVE_GEN.has(gen.status) ? "Generating…" : "Generate course book"}
          </button>
        }
      >
        <div className="row">
          <StatusBadge status={gen.status || "idle"} />
          <span className="muted">
            {gen.completed_sections || 0}/{gen.total_sections || 0} sections
            {gen.failed_sections ? ` · ${gen.failed_sections} failed` : ""}
          </span>
        </div>
        <div style={{ marginTop: 8 }}>
          <ProgressBar
            value={gen.completed_sections || 0}
            max={gen.total_sections || 1}
            tone={gen.status === "failed" ? "bad" : gen.status === "succeeded" ? "ok" : "accent"}
          />
        </div>
        {gen.last_error && <p className="error" style={{ marginBottom: 0 }}>Last error: {gen.last_error}</p>}
        {gen.next_retry_at && <p className="muted" style={{ marginBottom: 0 }}>Next retry: {gen.next_retry_at}</p>}
      </Panel>

      <Panel
        title="Outline"
        action={
          <span className="row" style={{ gap: 8 }}>
            {savedAt && <span className="muted" style={{ fontSize: 12 }}>saved {savedAt}</span>}
            <button className="btn-secondary" onClick={saveOutline} disabled={saving}>
              {saving ? "Saving…" : "Save outline"}
            </button>
          </span>
        }
      >
        {chapters.length === 0 ? (
          <p className="muted">No chapters.</p>
        ) : (
          chapters.map((ch, ci) => (
            <div key={ch.id || ci} style={{ marginBottom: 18 }}>
              <div className="row" style={{ gap: 8 }}>
                <input
                  style={{ maxWidth: 90 }}
                  value={ch.number || ""}
                  onChange={(e) => editChapter(ci, "number", e.target.value)}
                  aria-label="Chapter number"
                />
                <input value={ch.title || ""} onChange={(e) => editChapter(ci, "title", e.target.value)} aria-label="Chapter title" />
              </div>
              <ul className="list" style={{ marginTop: 8 }}>
                {(ch.sections || []).map((s, si) => (
                  <li key={s.id || si}>
                    <div className="row" style={{ gap: 8 }}>
                      <input
                        style={{ maxWidth: 90 }}
                        value={s.number || ""}
                        onChange={(e) => editSection(ci, si, "number", e.target.value)}
                        aria-label="Section number"
                      />
                      <input
                        value={s.title || ""}
                        onChange={(e) => editSection(ci, si, "title", e.target.value)}
                        aria-label="Section title"
                      />
                      <span className="row" style={{ gap: 6, flexShrink: 0 }}>
                        {(() => {
                          const st = sectionState(s);
                          return (
                            <Badge tone={st.tone} dot>
                              {st.label}
                            </Badge>
                          );
                        })()}
                        {s.completed && <Badge tone="ok">studied</Badge>}
                        <button className="btn-secondary" onClick={() => regenerate(s.id)} type="button">
                          Regenerate
                        </button>
                        <Link href={`/courses/${encodeURIComponent(id)}/sections/${encodeURIComponent(s.id)}`}>
                          Study →
                        </Link>
                      </span>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ))
        )}
      </Panel>
    </main>
  );
}
