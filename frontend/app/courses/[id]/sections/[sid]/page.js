"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api } from "../../../../lib/api";
import { Badge, ErrorBanner, MasteryBar, Panel, Spinner } from "../../../../components/ui";

const SUPPORT_TONE = { pdf_backed: "ok", course_inference: "warn", outside_knowledge: "bad" };

function SupportBadge({ status }) {
  if (!status) return null;
  return (
    <Badge tone={SUPPORT_TONE[status] || "muted"} dot>
      {String(status).replace(/_/g, " ")}
    </Badge>
  );
}

function SourceRefs({ refs }) {
  if (!refs || !refs.length) return null;
  return (
    <div style={{ marginTop: 4 }}>
      {refs.map((r, i) => (
        <span key={i} className="tag">
          {r}
        </span>
      ))}
    </div>
  );
}

export default function SectionPage() {
  const params = useParams();
  const id = decodeURIComponent(params.id);
  const sid = decodeURIComponent(params.sid);

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await api.getSection(id, sid));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [id, sid]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <Spinner label="Loading lesson…" />;
  if (!data) return <ErrorBanner error={error || "Section not found."} />;

  const section = data.section || {};
  const competencies = data.competencies || [];

  return (
    <main className="lesson-page">
      <div className="row" style={{ marginBottom: 16 }}>
        <div>
          <Link href={`/courses/${encodeURIComponent(id)}`} className="muted">
            ← {data.course_title || id}
          </Link>
          <h2 style={{ margin: "6px 0 0" }}>
            {section.number} {section.title}
          </h2>
        </div>
        <span className="row" style={{ gap: 8 }}>
          {section.is_assessment_section && <Badge tone="info" dot>{section.assessment_reason || "knowledge check"}</Badge>}
          {section.completed && <Badge tone="ok" dot>completed</Badge>}
        </span>
      </div>

      <ErrorBanner error={error} />

      <div className="lesson-layout">
        <div className="lesson-content">
          {section.lesson_goal && (
            <Panel title="Goal">
              <p style={{ margin: 0 }}>{section.lesson_goal}</p>
            </Panel>
          )}

          {section.learning_objectives && section.learning_objectives.length > 0 && (
            <Panel title="Learning objectives">
              <ul>
                {section.learning_objectives.map((o, i) => (
                  <li key={i}>{o}</li>
                ))}
              </ul>
            </Panel>
          )}

          {competencies.length > 0 && (
            <Panel title="Competencies">
              {competencies.map((c) => (
                <div key={c.id} style={{ marginBottom: 12 }}>
                  <div className="row">
                    <strong>{c.title}</strong>
                    <Badge tone="info">level {c.level}</Badge>
                  </div>
                  {c.description && <p className="muted" style={{ margin: "2px 0" }}>{c.description}</p>}
                  <MasteryBar percent={c.mastery ? c.mastery.mastery_percent : 0} />
                </div>
              ))}
            </Panel>
          )}

          <Concepts concepts={section.concepts} />
          <LessonBlocks blocks={section.lesson_blocks} />
          <WorkedExamples examples={section.worked_examples} />
          <Checks id={id} sid={sid} checks={section.checks} onGraded={load} />
          <Quiz id={id} sid={sid} quiz={section.mastery_quiz} onSubmitted={load} />
        </div>
        <aside className="tutor-sidebar">
          <TutorChat id={id} sid={sid} initial={section.chat_history} />
        </aside>
      </div>
    </main>
  );
}

function Concepts({ concepts }) {
  if (!concepts || !concepts.length) return null;
  return (
    <Panel title="Concepts">
      {concepts.map((c, i) => (
        <div key={c.id || i} style={{ marginBottom: 12 }}>
          <strong>{c.title}</strong>
          <p style={{ margin: "2px 0" }}>{c.explanation}</p>
          <SourceRefs refs={c.source_refs} />
        </div>
      ))}
    </Panel>
  );
}

function LessonBlocks({ blocks }) {
  if (!blocks || !blocks.length) return null;
  return (
    <Panel title="Lesson">
      {blocks.map((b, i) => (
        <div key={b.id || i} style={{ marginBottom: 14 }}>
          <div className="row">
            <strong>{b.title}</strong>
            <Badge tone="muted">{String(b.kind || "").replace(/_/g, " ")}</Badge>
          </div>
          <p style={{ margin: "4px 0", whiteSpace: "pre-wrap" }}>{b.body}</p>
        </div>
      ))}
    </Panel>
  );
}

function WorkedExamples({ examples }) {
  if (!examples || !examples.length) return null;
  return (
    <Panel title="Worked examples">
      {examples.map((w, i) => (
        <div key={w.id || i} style={{ marginBottom: 12 }}>
          <strong>{w.title}</strong>
          {w.prompt && <p style={{ margin: "2px 0" }}>{w.prompt}</p>}
          {w.steps && w.steps.length > 0 && (
            <ol>
              {w.steps.map((s, j) => (
                <li key={j}>{s}</li>
              ))}
            </ol>
          )}
        </div>
      ))}
    </Panel>
  );
}

function TutorChat({ id, sid, initial }) {
  const [turns, setTurns] = useState(initial || []);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function ask(e) {
    e.preventDefault();
    if (!question.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.chatSection(id, sid, question.trim());
      setTurns((t) => [...t, { question: question.trim(), ...res }]);
      setQuestion("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="tutor-chat">
      <div className="tutor-chat-head">
        <h2>Ask the tutor</h2>
      </div>
      <ErrorBanner error={error} />
      <div className="tutor-messages">
        {turns.length > 0 ? (
          turns.map((t, i) => (
            <div key={i} className="chat-turn">
              <div className="chat-bubble student">
                <strong>You</strong>
                <p>{t.question}</p>
              </div>
              <div className="chat-bubble tutor">
                <div className="row" style={{ gap: 8 }}>
                  <strong>Tutor</strong>
                  <SupportBadge status={t.support_status} />
                </div>
                <p style={{ whiteSpace: "pre-wrap" }}>{t.answer}</p>
                <SourceRefs refs={t.source_refs} />
              </div>
            </div>
          ))
        ) : (
          <p className="muted empty">Ask a question about this lesson.</p>
        )}
      </div>
      <form onSubmit={ask} className="tutor-composer">
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask a question about this lesson…"
        />
        <button type="submit" disabled={busy || !question.trim()} style={{ marginTop: 0, flexShrink: 0 }}>
          {busy ? "Asking…" : "Ask"}
        </button>
      </form>
    </section>
  );
}

const CONFIDENCE = [1, 2, 3, 4, 5, 6];

function Checks({ id, sid, checks, onGraded }) {
  if (!checks || !checks.length) return null;
  return (
    <Panel title="Knowledge checks">
      {checks.map((c) => (
        <CheckItem key={c.id} id={id} sid={sid} check={c} onGraded={onGraded} />
      ))}
    </Panel>
  );
}

function CheckItem({ id, sid, check, onGraded }) {
  const [answer, setAnswer] = useState("");
  const [confidence, setConfidence] = useState(4);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function grade(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.gradeCheck(id, sid, check.id, answer, Number(confidence));
      setResult(res);
      onGraded && onGraded();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={grade} style={{ marginBottom: 16, paddingBottom: 12, borderBottom: "1px solid var(--border)" }}>
      <div className="row">
        <strong>{check.prompt}</strong>
        <Badge tone="muted">{String(check.kind || "").replace(/_/g, " ")}</Badge>
      </div>
      {check.kind === "multiple_choice" && check.choices ? (
        <select value={answer} onChange={(e) => setAnswer(e.target.value)}>
          <option value="">Choose…</option>
          {check.choices.map((ch, i) => (
            <option key={i} value={ch}>
              {ch}
            </option>
          ))}
        </select>
      ) : (
        <textarea value={answer} onChange={(e) => setAnswer(e.target.value)} style={{ minHeight: 70 }} />
      )}
      <label>Confidence (1–6)</label>
      <select value={confidence} onChange={(e) => setConfidence(e.target.value)} style={{ maxWidth: 120 }}>
        {CONFIDENCE.map((n) => (
          <option key={n} value={n}>
            {n}
          </option>
        ))}
      </select>
      <ErrorBanner error={error} />
      <button type="submit" disabled={busy || !answer.trim()}>
        {busy ? "Grading…" : "Submit answer"}
      </button>
      {result && (
        <div className="panel" style={{ marginTop: 12, marginBottom: 0 }}>
          <div className="row">
            <Badge tone={result.passed ? "ok" : "bad"} dot>
              {result.passed ? "Passed" : "Keep practicing"} · {Math.round(result.score)}%
            </Badge>
          </div>
          {result.feedback && <p style={{ margin: "6px 0 0" }}>{result.feedback}</p>}
        </div>
      )}
    </form>
  );
}

function Quiz({ id, sid, quiz, onSubmitted }) {
  const [answers, setAnswers] = useState({});
  const [confidence, setConfidence] = useState(4);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  if (!quiz || !quiz.length) return null;

  const promptById = Object.fromEntries(quiz.map((q) => [q.id, q.prompt]));

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await api.submitQuiz(id, sid, answers, Number(confidence));
      setResult(res);
      onSubmitted && onSubmitted();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Chapter knowledge check">
      <form onSubmit={submit}>
        {quiz.map((q) => (
          <div key={q.id} style={{ marginBottom: 12 }}>
            <div className="row">
              <strong>{q.prompt}</strong>
              <Badge tone="muted">{q.kind}</Badge>
            </div>
            {q.kind === "multiple_choice" && q.choices && q.choices.length > 0 ? (
              <select
                value={answers[q.id] || ""}
                onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
              >
                <option value="">Choose…</option>
                {q.choices.map((choice, i) => (
                  <option key={i} value={choice}>
                    {choice}
                  </option>
                ))}
              </select>
            ) : (
              <textarea
                value={answers[q.id] || ""}
                onChange={(e) => setAnswers((a) => ({ ...a, [q.id]: e.target.value }))}
                style={{ minHeight: 64 }}
              />
            )}
          </div>
        ))}
        <label>Confidence (1–6)</label>
        <select value={confidence} onChange={(e) => setConfidence(e.target.value)} style={{ maxWidth: 120 }}>
          {CONFIDENCE.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        <ErrorBanner error={error} />
        <button type="submit" disabled={busy || Object.keys(answers).length === 0}>
          {busy ? "Submitting…" : "Submit quiz"}
        </button>
      </form>
      {result && (
        <div className="panel" style={{ marginTop: 12, marginBottom: 0 }}>
          <div className="row">
            <Badge tone={result.score >= 80 ? "ok" : result.score >= 40 ? "warn" : "bad"} dot>
              Score {Math.round(result.score)}%
            </Badge>
            {typeof result.passed === "boolean" && (
              <Badge tone={result.passed ? "ok" : "muted"}>{result.passed ? "passed" : "not yet"}</Badge>
            )}
          </div>
          {Array.isArray(result.items) && (
            <ul className="list" style={{ marginTop: 8 }}>
              {result.items.map((r) => (
                <li key={r.item_id}>
                  <div className="row">
                    <span>{promptById[r.item_id] || r.item_id}</span>
                    {typeof r.score === "number" && (
                      <Badge tone={r.score >= 80 ? "ok" : r.score >= 40 ? "warn" : "bad"}>{Math.round(r.score)}%</Badge>
                    )}
                  </div>
                  {r.feedback && <p className="muted" style={{ margin: "2px 0 0" }}>{r.feedback}</p>}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Panel>
  );
}
