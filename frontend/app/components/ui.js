// Reusable presentational components (no hooks — safe in server or client trees).

export function Panel({ title, action, children, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      {(title || action) && (
        <div className="panel-head">
          {title ? <h2>{title}</h2> : <span />}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

const TONE_BY_STATUS = {
  ready: "ok",
  succeeded: "ok",
  outline_draft: "info",
  idle: "muted",
  queued: "info",
  generating: "warn",
  running: "warn",
  retry_scheduled: "warn",
  needs_review: "warn",
  failed: "bad",
};

export function Badge({ children, tone = "muted", dot = false }) {
  return (
    <span className={`badge tone-${tone}`}>
      {dot && <span className={`dot ${tone}`} />}
      {children}
    </span>
  );
}

export function StatusBadge({ status }) {
  if (!status) return null;
  const tone = TONE_BY_STATUS[status] || "muted";
  return (
    <Badge tone={tone} dot>
      {String(status).replace(/_/g, " ")}
    </Badge>
  );
}

export function ProgressBar({ value = 0, max = 100, tone = "accent" }) {
  const pct = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div className="progress" role="progressbar" aria-valuenow={value} aria-valuemax={max}>
      <div className={`progress-fill tone-${tone}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

export function MasteryBar({ percent = 0, label = "Mastery" }) {
  const value = Math.round(percent || 0);
  const tone = value >= 80 ? "ok" : value >= 40 ? "warn" : "bad";
  return (
    <div className="mastery">
      <div className="mastery-row">
        <span className="muted">{label}</span>
        <span>{value}%</span>
      </div>
      <ProgressBar value={value} tone={tone} />
    </div>
  );
}

export function Spinner({ label = "Loading…" }) {
  return (
    <p className="spinner" role="status">
      <span className="spinner-dot" />
      {label}
    </p>
  );
}

export function EmptyState({ children }) {
  return <p className="muted empty">{children}</p>;
}

export function ErrorBanner({ error }) {
  if (!error) return null;
  const message = typeof error === "string" ? error : error.message || "Something went wrong.";
  return (
    <div className="error-banner" role="alert">
      {message}
    </div>
  );
}
