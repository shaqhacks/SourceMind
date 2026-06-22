"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_URL, api } from "./lib/api";
import { Badge, EmptyState, ErrorBanner, MasteryBar, Panel, Spinner, StatusBadge } from "./components/ui";

export default function Dashboard() {
  const [health, setHealth] = useState("checking");
  const [courses, setCourses] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [due, setDue] = useState(null);
  const [notifications, setNotifications] = useState(null);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [busyCourseId, setBusyCourseId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    api
      .health()
      .then((h) => setHealth(h && h.status === "ok" ? "ok" : "bad"))
      .catch(() => setHealth("bad"));

    Promise.allSettled([api.listCourses(includeArchived), api.listSubjects(), api.dueReviews(false), api.notifications(true)])
      .then(([c, s, d, n]) => {
        if (c.status === "fulfilled") setCourses((c.value && c.value.courses) || []);
        else setError(c.reason && c.reason.message);
        if (s.status === "fulfilled") setSubjects((s.value && s.value.subjects) || []);
        if (d.status === "fulfilled") setDue(d.value);
        if (n.status === "fulfilled") setNotifications(n.value);
      })
      .finally(() => setLoading(false));
  }, [includeArchived]);

  async function updateCourse(id, action) {
    setBusyCourseId(id);
    setError(null);
    try {
      const updated =
        action === "archive"
          ? await api.archiveCourse(id)
          : action === "restore"
            ? await api.restoreCourse(id)
            : null;
      setCourses((items) =>
        action === "archive" && !includeArchived
          ? items.filter((course) => course.course_id !== id)
          : items.map((course) =>
              course.course_id === id
                ? { ...course, archived: Boolean(updated && updated.archived_at), archived_at: updated ? updated.archived_at : course.archived_at }
                : course
            )
      );
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyCourseId(null);
    }
  }

  async function removeCourse(id, title) {
    if (!window.confirm(`Delete "${title || id}" permanently?`)) return;
    setBusyCourseId(id);
    setError(null);
    try {
      await api.deleteCourse(id);
      setCourses((items) => items.filter((course) => course.course_id !== id));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusyCourseId(null);
    }
  }

  return (
    <main>
      <div className="row" style={{ marginBottom: 20 }}>
        <Badge tone={health === "ok" ? "ok" : health === "bad" ? "bad" : "muted"} dot>
          {health === "ok" ? "Backend connected" : health === "bad" ? "Backend unreachable" : "Checking…"}
        </Badge>
        <span className="muted" style={{ fontSize: 13 }}>{API_URL}</span>
      </div>

      <div className="grid" style={{ marginBottom: 20 }}>
        <Panel>
          <div className="stat-label">Courses</div>
          <div className="stat">{courses.length}</div>
        </Panel>
        <Panel>
          <div className="stat-label">Subjects</div>
          <div className="stat">{subjects.length}</div>
        </Panel>
        <Panel>
          <div className="stat-label">Reviews due</div>
          <div className="stat">{due ? due.due_count ?? (due.items || []).length : "—"}</div>
          {due && <Link href="/reviews">View reviews →</Link>}
        </Panel>
        <Panel>
          <div className="stat-label">Notifications</div>
          <div className="stat">{notifications ? notifications.unread_count ?? 0 : "—"}</div>
          {notifications && <Link href="#notifications">Open reminders ↓</Link>}
        </Panel>
      </div>

      <ErrorBanner error={error} />

      <Panel title="Notifications" action={<Link href="/reviews">Review queue →</Link>}>
        {loading ? (
          <Spinner />
        ) : notifications && notifications.items && notifications.items.length > 0 ? (
          <div className="grid" id="notifications">
            {notifications.items.slice(0, 6).map((item) => (
              <Link key={item.id} href={item.href} className="card-link panel">
                <div className="row">
                  <strong>{item.title}</strong>
                  <Badge tone={item.due ? "warn" : "muted"} dot>
                    {item.urgency}
                  </Badge>
                </div>
                <p className="muted" style={{ margin: "4px 0 0", fontSize: 13 }}>
                  {item.message}
                </p>
                {item.next_review_at && (
                  <p className="muted" style={{ margin: "4px 0 0", fontSize: 12 }}>
                    {item.next_review_at}
                  </p>
                )}
              </Link>
            ))}
          </div>
        ) : (
          <EmptyState>No review reminders right now.</EmptyState>
        )}
      </Panel>

      <Panel
        title="Courses"
        action={
          <span className="row" style={{ gap: 10 }}>
            <label className="row" style={{ gap: 6, margin: 0 }}>
              <input
                type="checkbox"
                checked={includeArchived}
                onChange={(e) => setIncludeArchived(e.target.checked)}
                style={{ width: "auto" }}
              />
              <span className="muted">Archived</span>
            </label>
            <Link href="/upload">+ New</Link>
          </span>
        }
      >
        {loading ? (
          <Spinner />
        ) : courses.length === 0 ? (
          <EmptyState>No courses yet. Upload sources to create one.</EmptyState>
        ) : (
          <div className="grid">
            {courses.map((c) => (
              <div key={c.course_id} className="panel course-card">
                <div className="row">
                  <Link href={`/courses/${encodeURIComponent(c.course_id)}`}>
                    <strong>{c.title || c.course_id}</strong>
                  </Link>
                  <span className="row" style={{ gap: 6 }}>
                    {c.archived && <Badge tone="muted">archived</Badge>}
                    <StatusBadge status={c.status} />
                  </span>
                </div>
                <MasteryBar percent={c.mastery_percent || 0} />
                <p className="muted" style={{ margin: "4px 0 0", fontSize: 13 }}>
                  {c.generation_status ? `${String(c.generation_status).replace(/_/g, " ")} · ` : ""}
                  {c.generation_completed_sections ?? 0}/{c.generation_total_sections ?? c.sections_count ?? 0} sections
                  {c.competencies_count != null ? ` · ${c.competencies_count} competencies` : ""}
                </p>
                {c.generation_last_error && (
                  <p className="error" style={{ margin: "4px 0 0", fontSize: 12 }}>{c.generation_last_error}</p>
                )}
                <div className="row" style={{ gap: 8, marginTop: 12 }}>
                  <button
                    className="btn-secondary"
                    type="button"
                    onClick={() => updateCourse(c.course_id, c.archived ? "restore" : "archive")}
                    disabled={busyCourseId === c.course_id}
                  >
                    {c.archived ? "Restore" : "Archive"}
                  </button>
                  <button
                    className="btn-danger"
                    type="button"
                    onClick={() => removeCourse(c.course_id, c.title)}
                    disabled={busyCourseId === c.course_id}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel title={`Subjects (${subjects.length})`}>
        {loading ? (
          <Spinner />
        ) : subjects.length === 0 ? (
          <EmptyState>No subjects yet.</EmptyState>
        ) : (
          <ul className="list">
            {subjects.map((id) => (
              <li key={id}>{id}</li>
            ))}
          </ul>
        )}
      </Panel>
    </main>
  );
}
