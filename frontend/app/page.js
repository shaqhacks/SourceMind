"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { library } from "./lib/api";
import { Badge, EmptyState, ErrorBanner, Panel, Spinner, StatusBadge } from "./components/ui";

function GenerationProgress({ course }) {
  const prog = course.generation_progress;
  if (!prog) return null;
  const completed = prog.completed ?? 0;
  const total = prog.total ?? 0;
  const failed = prog.failed ?? 0;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
  return (
    <div style={{ marginTop: 6 }}>
      <div
        style={{
          height: 4,
          borderRadius: 2,
          background: "var(--border, #e2e8f0)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            background: "var(--accent, #6366f1)",
            borderRadius: 2,
            transition: "width 0.3s ease",
          }}
        />
      </div>
      <p className="muted" style={{ margin: "3px 0 0", fontSize: 12 }}>
        {completed}/{total} chapters generated{failed > 0 ? ` · ${failed} failed` : ""}
      </p>
    </div>
  );
}

export default function Dashboard() {
  const [courses, setCourses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    library
      .listCourses()
      .then((data) => {
        // backend may return array directly or wrapped in { courses: [...] }
        setCourses(Array.isArray(data) ? data : (data && data.courses) || []);
      })
      .catch((err) => setError(err.message || "Failed to load courses"))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main>
      <div className="row" style={{ alignItems: "center", marginBottom: 24, gap: 16 }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ margin: 0, fontSize: "1.5rem", fontWeight: 700 }}>My Library</h1>
          <p className="muted" style={{ margin: "4px 0 0", fontSize: 14 }}>
            Your uploaded courses and study materials
          </p>
        </div>
        <Link
          href="/upload"
          className="btn-primary"
          style={{
            display: "inline-block",
            padding: "10px 20px",
            borderRadius: 8,
            fontWeight: 600,
            fontSize: 14,
            textDecoration: "none",
          }}
        >
          + Upload PDF
        </Link>
      </div>

      <ErrorBanner error={error} />

      {loading ? (
        <Panel>
          <Spinner />
        </Panel>
      ) : courses.length === 0 ? (
        <Panel>
          <EmptyState>
            No courses yet — upload a PDF to begin.{" "}
            <Link href="/upload" style={{ fontWeight: 600 }}>
              Upload now →
            </Link>
          </EmptyState>
        </Panel>
      ) : (
        <div className="grid">
          {courses.map((c) => {
            const courseId = c.id ?? c.course_id;
            const title = c.title || courseId;
            const status = c.status;
            const genStatus = c.generation_status;

            return (
              <Link
                key={courseId}
                href={`/courses/${encodeURIComponent(courseId)}`}
                className="panel card-link"
                style={{ textDecoration: "none", display: "block" }}
              >
                <div className="row course-card-head" style={{ alignItems: "flex-start", gap: 8 }}>
                  <strong
                    className="course-card-title"
                    style={{ flex: 1, fontSize: "1rem", lineHeight: 1.4 }}
                  >
                    {title}
                  </strong>
                  <span className="row" style={{ gap: 6, flexShrink: 0 }}>
                    {status && <StatusBadge status={status} />}
                  </span>
                </div>

                {genStatus && (
                  <p className="muted" style={{ margin: "4px 0 0", fontSize: 12 }}>
                    {String(genStatus).replace(/_/g, " ")}
                  </p>
                )}

                <GenerationProgress course={c} />
              </Link>
            );
          })}
        </div>
      )}
    </main>
  );
}
