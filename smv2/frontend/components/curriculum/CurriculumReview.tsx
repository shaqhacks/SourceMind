"use client";

import { useCallback, useEffect, useState } from "react";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import {
  createCurriculumDraft,
  editCurriculumClaim,
  editCurriculumConcept,
  getCurriculum,
  listEvidenceMappings,
  publishCurriculum,
  reviewEvidenceMapping,
  type CurriculumVersionOut,
  type EvidenceMappingReviewOut,
} from "@/lib/api/client";

export default function CurriculumReview({ courseId }: { courseId: string }) {
  const [draft, setDraft] = useState<CurriculumVersionOut | null>(null);
  const [mappings, setMappings] = useState<EvidenceMappingReviewOut[]>([]);
  const [conceptEdits, setConceptEdits] = useState<Record<string, { label: string; description_md: string }>>({});
  const [claimEdits, setClaimEdits] = useState<Record<string, string>>({});
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (isActive: () => boolean = () => true) => {
    if (!isActive()) return;
    setLoading(true);
    const [curriculumResult, mappingResult] = await Promise.all([
      getCurriculum(courseId, "draft"),
      listEvidenceMappings(courseId),
    ]);
    if (!isActive()) return;
    setDraft(curriculumResult.data ?? null);
    setMappings(mappingResult.data ?? []);
    if (curriculumResult.data) {
      setConceptEdits(Object.fromEntries(curriculumResult.data.concepts.map((concept) => [
        concept.id,
        { label: concept.label, description_md: concept.description_md },
      ])));
      setClaimEdits(Object.fromEntries(curriculumResult.data.claims.map((claim) => [claim.id, claim.statement])));
    }
    setLoading(false);
  }, [courseId]);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => void load(() => active));
    return () => {
      active = false;
    };
  }, [load]);

  async function createDraft() {
    const result = await createCurriculumDraft(courseId, "Instructor review draft");
    if (!result.data) {
      setMessage("Could not create a review draft.");
      return;
    }
    setMessage("Review draft created from the published curriculum.");
    await load();
  }

  async function saveConcept(conceptId: string) {
    if (!draft) return;
    const original = draft.concepts.find((concept) => concept.id === conceptId);
    const edit = conceptEdits[conceptId];
    if (!original || !edit) return;
    const result = await editCurriculumConcept(draft.id, conceptId, {
      label: edit.label,
      description_md: edit.description_md,
      aliases: original.aliases,
      chapter_label: original.chapter_label,
    });
    setMessage(result.ok ? "Concept saved in this draft." : "Concept could not be saved.");
  }

  async function saveClaim(claimId: string) {
    if (!draft) return;
    const result = await editCurriculumClaim(draft.id, claimId, { statement: claimEdits[claimId] });
    setMessage(result.ok ? "Learning claim saved in this draft." : "Learning claim could not be saved.");
  }

  async function setMappingReview(mappingId: string, reviewState: "verified" | "rejected") {
    const result = await reviewEvidenceMapping(mappingId, reviewState);
    if (result.data) {
      setMappings((current) => current.map((mapping) => mapping.id === mappingId ? result.data! : mapping));
      setMessage(`Mapping ${reviewState}.`);
    } else {
      setMessage("Mapping review could not be recorded.");
    }
  }

  async function publish() {
    if (!draft) return;
    const result = await publishCurriculum(draft.id);
    setMessage(result.ok ? "Curriculum published. Historical evidence keeps its original mapping version." : "Curriculum could not be published.");
    if (result.ok) setDraft(null);
  }

  if (loading) return <p role="status" className="p-8 text-sm text-muted-foreground">Loading curriculum review…</p>;

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-9 py-8">
      <div>
        <h1 className="text-[34px]">Curriculum review</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Review book-derived concepts, observable claims, and item mappings. Draft edits never rewrite historical evidence.
        </p>
      </div>
      {message && <p role="status" className="rounded-md bg-accent-soft px-4 py-2 text-sm">{message}</p>}

      {!draft ? (
        <Card className="flex items-center justify-between gap-4">
          <p className="text-sm">Create a new version before editing the published curriculum.</p>
          <Button variant="primary" onClick={() => void createDraft()}>Create review draft</Button>
        </Card>
      ) : (
        <>
          <section className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-semibold">Concepts and learning claims</h2>
              <Button variant="primary" onClick={() => void publish()}>Publish reviewed version</Button>
            </div>
            {draft.concepts.map((concept) => (
              <Card key={concept.id} className="flex flex-col gap-3">
                <label className="text-sm font-semibold">
                  Concept label {concept.label}
                  <input
                    aria-label={`Concept label ${concept.label}`}
                    value={conceptEdits[concept.id]?.label ?? concept.label}
                    onChange={(event) => setConceptEdits((current) => ({
                      ...current,
                      [concept.id]: { ...current[concept.id], label: event.target.value },
                    }))}
                    className="mt-1 block w-full rounded-md border border-divider bg-background px-3 py-2 font-normal"
                  />
                </label>
                <textarea
                  aria-label={`Concept description ${concept.label}`}
                  value={conceptEdits[concept.id]?.description_md ?? concept.description_md}
                  onChange={(event) => setConceptEdits((current) => ({
                    ...current,
                    [concept.id]: { ...current[concept.id], description_md: event.target.value },
                  }))}
                  className="min-h-20 rounded-md border border-divider bg-background px-3 py-2 text-sm"
                />
                <Button size="sm" className="self-start" onClick={() => void saveConcept(concept.id)}>Save concept</Button>
                {draft.claims.filter((claim) => claim.concept_id === concept.id).map((claim) => (
                  <div key={claim.id} className="border-l-2 border-divider pl-4">
                    <label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Observable claim</label>
                    <textarea
                      aria-label={`Learning claim ${claim.statement}`}
                      value={claimEdits[claim.id] ?? claim.statement}
                      onChange={(event) => setClaimEdits((current) => ({ ...current, [claim.id]: event.target.value }))}
                      className="mt-1 min-h-16 w-full rounded-md border border-divider bg-background px-3 py-2 text-sm"
                    />
                    <Button size="sm" onClick={() => void saveClaim(claim.id)}>Save claim</Button>
                  </div>
                ))}
              </Card>
            ))}
          </section>
        </>
      )}

      <section className="flex flex-col gap-3">
        <h2 className="text-xl font-semibold">Question and card mappings</h2>
        {mappings.length === 0 ? <p className="text-sm text-muted-foreground">No mappings are ready for review.</p> : mappings.map((mapping) => (
          <Card key={mapping.id} className="flex flex-col gap-2">
            <p className="font-semibold">{mapping.item_preview || `${mapping.item_type} item`}</p>
            <p className="text-sm text-muted-foreground">{mapping.concept_label} · {mapping.claim_statement}</p>
            <p className="text-xs text-muted-foreground">{mapping.task_type} · {mapping.review_state}{mapping.mapping_confidence == null ? "" : ` · ${Math.round(mapping.mapping_confidence * 100)}% mapping confidence`}</p>
            <div className="flex gap-2">
              <Button size="sm" variant="primary" onClick={() => void setMappingReview(mapping.id, "verified")}>Verify mapping</Button>
              <Button size="sm" variant="danger" onClick={() => void setMappingReview(mapping.id, "rejected")}>Reject mapping</Button>
            </div>
          </Card>
        ))}
      </section>
    </div>
  );
}
