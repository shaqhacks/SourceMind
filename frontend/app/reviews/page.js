"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "../lib/api";
import { Badge, EmptyState, ErrorBanner, MasteryBar, Panel, Spinner } from "../components/ui";

function ReviewCard({ item }) {
  const href = `/courses/${encodeURIComponent(item.course_id)}/sections/${encodeURIComponent(item.section_id)}`;
  return (
    <Link href={href} className="card-link panel">
      <div className="row">
        <strong>{item.competency_title || item.competency_id}</strong>
        {item.due ? <Badge tone="warn" dot>due</Badge> : <Badge tone="muted" dot>upcoming</Badge>}
      </div>
      <p className="muted" style={{ margin: "2px 0", fontSize: 13 }}>
        {item.course_title} · {item.section_number} {item.section_title}
      </p>
      <MasteryBar percent={item.mastery_percent || 0} />
      <p className="muted" style={{ margin: "4px 0 0", fontSize: 12 }}>
        {item.reason ? `${item.reason} · ` : ""}
        {item.next_review_at ? `next: ${item.next_review_at}` : ""}
        {typeof item.last_score === "number" ? ` · last ${Math.round(item.last_score)}%` : ""}
      </p>
    </Link>
  );
}

export default function Reviews() {
  const [data, setData] = useState(null);
  const [includeUpcoming, setIncludeUpcoming] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await api.dueReviews(includeUpcoming));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [includeUpcoming]);

  useEffect(() => {
    load();
  }, [load]);

  const items = (data && data.items) || [];
  const dueItems = items.filter((i) => i.due);
  const upcoming = items.filter((i) => !i.due);

  return (
    <main>
      <div className="row" style={{ marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>Spaced review</h2>
        <label className="row" style={{ gap: 6, margin: 0 }}>
          <input
            type="checkbox"
            checked={includeUpcoming}
            onChange={(e) => setIncludeUpcoming(e.target.checked)}
            style={{ width: "auto" }}
          />
          <span className="muted">Show upcoming</span>
        </label>
      </div>

      <ErrorBanner error={error} />

      {loading ? (
        <Spinner label="Loading reviews…" />
      ) : (
        <>
          <Panel title={`Due now (${data ? data.due_count ?? dueItems.length : 0})`}>
            {dueItems.length === 0 ? (
              <EmptyState>Nothing due. Great work — check back later.</EmptyState>
            ) : (
              <div className="grid">
                {dueItems.map((it) => (
                  <ReviewCard key={`${it.course_id}:${it.competency_id}`} item={it} />
                ))}
              </div>
            )}
          </Panel>

          {includeUpcoming && (
            <Panel title={`Upcoming (${data ? data.upcoming_count ?? upcoming.length : 0})`}>
              {upcoming.length === 0 ? (
                <EmptyState>No upcoming reviews scheduled.</EmptyState>
              ) : (
                <div className="grid">
                  {upcoming.map((it) => (
                    <ReviewCard key={`${it.course_id}:${it.competency_id}`} item={it} />
                  ))}
                </div>
              )}
            </Panel>
          )}
        </>
      )}
    </main>
  );
}
