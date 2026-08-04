"use client";

import { useCallback, useEffect, useState } from "react";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import {
  getDiagnosticValidationSummary,
  getNextDiagnosticValidation,
  recordDiagnosticDisagreementReason,
  submitDiagnosticJudgment,
  type DiagnosticBlindCaseOut,
  type DiagnosticJudgmentIn,
  type DiagnosticJudgmentOut,
  type DiagnosticValidationSummaryOut,
} from "@/lib/api/client";

const JUDGMENTS: Array<{ value: DiagnosticJudgmentIn["judgment"]; label: string }> = [
  { value: "insufficient", label: "Insufficient evidence" },
  { value: "not_struggling", label: "Not struggling" },
  { value: "uncertain", label: "Uncertain" },
  { value: "likely_struggling", label: "Likely struggling" },
];

const REASONS = [
  ["model_estimate", "Model estimate"],
  ["item_mapping", "Item mapping"],
  ["concept_granularity", "Concept granularity"],
  ["insufficient_student_evidence", "Insufficient student evidence"],
  ["instructor_disagreement", "Instructor disagreement"],
] as const;

export default function DiagnosticValidation({ courseId }: { courseId: string }) {
  const [caseData, setCaseData] = useState<DiagnosticBlindCaseOut | null>(null);
  const [result, setResult] = useState<DiagnosticJudgmentOut | null>(null);
  const [summary, setSummary] = useState<DiagnosticValidationSummaryOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async (isActive: () => boolean = () => true) => {
    if (!isActive()) return;
    setLoading(true);
    const [next, aggregate] = await Promise.all([
      getNextDiagnosticValidation(courseId),
      getDiagnosticValidationSummary(courseId),
    ]);
    if (!isActive()) return;
    setCaseData(next.data ?? null);
    setSummary(aggregate.data ?? null);
    setResult(null);
    setLoading(false);
  }, [courseId]);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => void load(() => active));
    return () => {
      active = false;
    };
  }, [load]);

  async function judge(judgment: DiagnosticJudgmentIn["judgment"]) {
    if (!caseData) return;
    const response = await submitDiagnosticJudgment(courseId, {
      concept_id: caseData.concept_id,
      judgment,
      disagreement_reason: null,
      notes_md: null,
    });
    if (response.data) setResult(response.data);
    else setMessage("The judgment could not be recorded.");
  }

  async function explainDisagreement(reason: typeof REASONS[number][0]) {
    if (!result) return;
    const response = await recordDiagnosticDisagreementReason(courseId, result.id, reason);
    if (response.data) {
      setResult(response.data);
      setMessage("Disagreement reason recorded.");
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-9 py-8">
      <div>
        <h1 className="text-[34px]">Validate learning signals</h1>
        <p className="mt-1 text-sm text-muted-foreground">Judge the concept first. SourceMind reveals its estimate only after your judgment is recorded.</p>
      </div>
      {message && <p role="status" className="rounded-md bg-accent-soft px-4 py-2 text-sm">{message}</p>}
      {loading ? <p role="status" className="text-sm text-muted-foreground">Loading blinded case…</p> : !caseData ? (
        <Card><p className="text-sm">No unreviewed concept estimates are available.</p></Card>
      ) : (
        <Card className="flex flex-col gap-4 p-6">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Blinded concept review</p>
            <h2 className="mt-1 text-2xl font-semibold">{caseData.concept_label}</h2>
            <p className="mt-2 text-sm text-muted-foreground">{caseData.concept_description_md}</p>
          </div>
          {!result ? (
            <div className="grid grid-cols-2 gap-2">
              {JUDGMENTS.map((item) => <Button key={item.value} onClick={() => void judge(item.value)}>{item.label}</Button>)}
            </div>
          ) : (
            <div className="flex flex-col gap-3 rounded-md border border-divider p-4">
              <p className="font-semibold">SourceMind: {result.model_state.replaceAll("_", " ")}{result.readiness_estimate == null ? "" : ` · ${Math.round(result.readiness_estimate * 100)}% readiness`}</p>
              <p className="text-sm text-muted-foreground">Based on {result.evidence_count} distinct items using {result.model_version}.</p>
              <p className="text-sm">{result.agreement ? "The model agrees with your judgment." : "The model differs from your judgment."}</p>
              {result.requires_disagreement_reason ? (
                <div>
                  <p className="mb-2 text-sm font-semibold">What best explains the disagreement?</p>
                  <div className="flex flex-wrap gap-2">
                    {REASONS.map(([value, label]) => <Button key={value} size="sm" onClick={() => void explainDisagreement(value)}>{label}</Button>)}
                  </div>
                </div>
              ) : <Button variant="primary" className="self-start" onClick={() => void load()}>Next concept</Button>}
            </div>
          )}
        </Card>
      )}
      {summary && (
        <Card className="flex flex-col gap-2">
          <h2 className="font-semibold">Agreement summary</h2>
          <p className="text-sm">{summary.sample_size} completed reviews · {summary.raw_agreement == null ? "agreement pending" : `${Math.round(summary.raw_agreement * 100)}% raw agreement`}</p>
          {!summary.sufficient_sample && <p className="text-xs text-muted-foreground">Sample is too small for a stable agreement claim.</p>}
          {summary.pending_reason_count > 0 && <p className="text-xs text-muted-foreground">{summary.pending_reason_count} disagreement reason pending.</p>}
        </Card>
      )}
    </div>
  );
}
