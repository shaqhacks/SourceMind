"use client";

import Link from "next/link";
import { Check, Copy } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import EmptyState from "@/components/ui/EmptyState";
import Skeleton from "@/components/ui/Skeleton";
import {
  addCurriculumConcept,
  addCurriculumRelation,
  createCurriculumDraft,
  deleteCurriculumConcept,
  deleteCurriculumRelation,
  editCurriculumConcept,
  getCurriculum,
  getSkillMapUploadTemplate,
  getSkillStatus,
  listSections,
  publishCurriculum,
  startCurriculumExtraction,
  uploadSkillMap,
  type CurriculumVersionOut,
  type SectionOut,
  type SkillMapUploadConceptIn,
  type SkillStatusOut,
} from "@/lib/api/client";
import { describeError, type FetchError } from "@/lib/api/errors";
import SkillMapGraphPreview from "./SkillMapGraphPreview";
import { useCourseTitle } from "./useCourseTitle";

export interface SkillMapEditorProps {
  courseId: string;
}

interface ConceptDraft {
  label: string;
  description_md: string;
  section_id: string;
}

type Edges = { relation_id: string; from: string; to: string }[];

/**
 * Draft-scoped skill map editor (ADR-030). Reads the draft curriculum
 * version (getCurriculum view=draft), edits concepts/prerequisite edges via
 * the versioned-curriculum endpoints, and publishes the draft so the
 * learner-facing skill map/detail update. Mutations only ever touch the
 * draft; learner evidence history is untouched until Publish.
 */
export default function SkillMapEditor({ courseId }: SkillMapEditorProps) {
  const { title: courseTitle, error: titleError, reload: reloadTitle } = useCourseTitle(courseId);

  const [draft, setDraft] = useState<CurriculumVersionOut | null>(null);
  const [sections, setSections] = useState<SectionOut[]>([]);
  const [status, setStatus] = useState<SkillStatusOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<FetchError | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, ConceptDraft>>({});

  // Add-concept form state.
  const [newSlug, setNewSlug] = useState("");
  const [newLabel, setNewLabel] = useState("");
  // Add-edge form state (concept ids).
  const [edgeFrom, setEdgeFrom] = useState("");
  const [edgeTo, setEdgeTo] = useState("");

  // Upload-a-skill-map form state.
  const [showUpload, setShowUpload] = useState(false);
  const [uploadJson, setUploadJson] = useState("");
  const [uploadTemplate, setUploadTemplate] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [copied, setCopied] = useState(false);

  const contentSections = useMemo(
    () => sections.filter((section) => section.kind === "content"),
    [sections],
  );

  const load = useCallback(
    async (isActive: () => boolean = () => true) => {
      const [draftResult, sectionsResult] = await Promise.all([
        getCurriculum(courseId, "draft"),
        listSections(courseId),
      ]);
      if (!isActive()) return;
      setDraft(draftResult.data ?? null);
      setSections(sectionsResult.data ?? []);
      if (draftResult.data) {
        setEdits(
          Object.fromEntries(
            draftResult.data.concepts.map((concept) => [
              concept.id,
              {
                label: concept.label,
                description_md: concept.description_md,
                section_id: concept.section_id ?? "",
              },
            ]),
          ),
        );
      } else {
        setEdits({});
      }
      setLoading(false);
    },
    [courseId],
  );

  const refreshStatus = useCallback(async (isActive: () => boolean = () => true) => {
    const { data } = await getSkillStatus(courseId);
    if (isActive() && data) setStatus(data);
  }, [courseId]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    queueMicrotask(() => {
      void load(() => active);
      void refreshStatus(() => active);
    });
    return () => {
      active = false;
    };
  }, [load, refreshStatus]);

  // Poll while a generation is in flight so the editor flips from
  // "generating" to the loaded draft on its own.
  useEffect(() => {
    if (status?.phase !== "generating") return;
    let active = true;
    const timer = setInterval(async () => {
      const { data } = await getSkillStatus(courseId);
      if (!active) return;
      if (data) setStatus(data);
      if (data && data.phase !== "generating") void load(() => active);
    }, 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [status?.phase, courseId, load]);

  async function reload() {
    setMessage(null);
    await load();
    await refreshStatus();
  }

  async function run<T>(fn: () => Promise<T>, ok: string): Promise<void> {
    setMessage(null);
    const result = await fn();
    setMessage((result as { ok?: boolean } | undefined)?.ok === false ? "Save failed." : ok);
    await reload();
  }

  function chapterLabelFor(sectionId: string, fallback: string | null): string | null {
    if (!sectionId) return fallback;
    return contentSections.find((s) => s.id === sectionId)?.chapter_label ?? fallback;
  }

  async function saveConcept(conceptId: string) {
    const original = draft?.concepts.find((c) => c.id === conceptId);
    const edit = edits[conceptId];
    if (!draft || !original || !edit) return;
    await run(
      () =>
        editCurriculumConcept(draft.id, conceptId, {
          label: edit.label,
          description_md: edit.description_md,
          aliases: original.aliases,
          chapter_label: chapterLabelFor(edit.section_id, original.chapter_label),
          section_id: edit.section_id || null,
        }),
      "Concept saved.",
    );
  }

  async function deleteConcept(conceptId: string) {
    if (!draft) return;
    await run(() => deleteCurriculumConcept(draft.id, conceptId), "Concept removed.");
  }

  async function handleAddConcept() {
    if (!draft) return;
    const slug = newSlug.trim() || newLabel.trim().toLowerCase().replace(/\s+/g, "-");
    if (!slug || !newLabel.trim()) return;
    await run(
      () =>
        addCurriculumConcept(draft.id, {
          stable_key: slug,
          label: newLabel.trim(),
          description_md: "",
          aliases: [],
          chapter_label: null,
          section_id: null,
        }),
      "Concept added.",
    );
    setNewSlug("");
    setNewLabel("");
  }

  async function handleAddEdge() {
    if (!draft || !edgeFrom || !edgeTo) return;
    if (edgeFrom === edgeTo) return;
    const duplicate = edges.some(
      (edge) =>
        (edge.from === edgeFrom && edge.to === edgeTo) ||
        (edge.from === edgeTo && edge.to === edgeFrom),
    );
    if (duplicate) {
      setMessage("That prerequisite (or its reverse) already exists.");
      return;
    }
    await run(
      () => addCurriculumRelation(draft.id, { from_concept_id: edgeFrom, to_concept_id: edgeTo, kind: "requires" }),
      "Prerequisite added.",
    );
    setEdgeFrom("");
    setEdgeTo("");
  }

  async function handlePublish() {
    if (!draft) return;
    const result = await publishCurriculum(draft.id);
    setMessage(result.ok ? "Published — the learner skill map now reflects your edits." : "Publish failed.");
    await reload();
  }

  async function handleGenerate() {
    setMessage(null);
    await startCurriculumExtraction(courseId);
    await refreshStatus();
    await load();
  }

  async function handleStartEditing() {
    setMessage(null);
    const result = await createCurriculumDraft(courseId);
    if (!result.ok) {
      setMessage("Could not create an editable draft.");
      return;
    }
    await load();
    await refreshStatus();
  }

  async function handleShowTemplate() {
    if (uploadTemplate !== null) return;
    const { data } = await getSkillMapUploadTemplate(courseId);
    if (data) setUploadTemplate(data.prompt);
  }

  async function handleCopyTemplate() {
    if (!uploadTemplate) return;
    try {
      await navigator.clipboard.writeText(uploadTemplate);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setMessage("Could not copy to clipboard.");
    }
  }

  async function handleUpload() {
    let parsed: unknown;
    try {
      parsed = JSON.parse(uploadJson);
    } catch {
      setMessage("That isn't valid JSON — check the pasted text and try again.");
      return;
    }
    const concepts = (parsed as { concepts?: unknown })?.concepts;
    if (!Array.isArray(concepts) || concepts.length === 0) {
      setMessage("The JSON needs a non-empty 'concepts' array.");
      return;
    }
    setMessage(null);
    setUploading(true);
    const result = await uploadSkillMap(courseId, {
      concepts: concepts as SkillMapUploadConceptIn[],
    });
    setUploading(false);
    if (!result.ok) {
      const detail = (result.error as { detail?: unknown } | undefined)?.detail;
      setMessage(
        typeof detail === "string" && detail
          ? detail
          : `Upload failed (HTTP ${result.status ?? "unknown"}).`,
      );
      return;
    }
    const data = result.data;
    const unmatched = data?.unmatched_sections?.length
      ? ` · ${data.unmatched_sections.length} chapter reference${
          data.unmatched_sections.length === 1 ? "" : "s"
        } left unlinked`
      : "";
    setMessage(
      `Uploaded ${data?.concept_count ?? 0} skills${unmatched} — review and publish when ready.`,
    );
    setShowUpload(false);
    setUploadJson("");
    setUploadTemplate(null);
    await load();
    await refreshStatus();
  }

  const edges: Edges = useMemo(
    () =>
      (draft?.relations ?? [])
        .filter((relation) => relation.kind === "requires" && relation.to_concept_id)
        .map((relation) => ({
          relation_id: relation.id,
          from: relation.from_concept_id,
          to: relation.to_concept_id as string,
        })),
    [draft],
  );

  const conceptById = useMemo(
    () => new Map((draft?.concepts ?? []).map((c) => [c.id, c])),
    [draft],
  );

  const errorBanner = titleError ?? error;
  if (errorBanner) {
    return (
      <div className="mx-auto w-full max-w-[1100px] px-9 py-8">
        <ErrorBanner
          status={errorBanner.status}
          message={errorBanner.message}
          onRetry={() => (titleError ? reloadTitle() : reload())}
        />
      </div>
    );
  }

  if (loading || courseTitle === null) {
    return (
      <div className="mx-auto flex w-full max-w-[1100px] flex-col gap-4 px-9 py-8">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-9 w-96" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-[1100px] flex-col gap-6 px-9 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="mb-1 text-sm font-semibold">
            <Link href={`/course/${courseId}`} className="text-accent-700 hover:underline">
              {courseTitle}
            </Link>
            <span className="text-muted-foreground opacity-60"> / </span>
            <Link href={`/course/${courseId}/skills`} className="text-accent-700 hover:underline">
              Skill map
            </Link>
            <span className="text-muted-foreground opacity-60"> / </span>
            <span className="text-muted-foreground">Edit</span>
          </p>
          <h1 className="text-[34px]">Edit skill map — {courseTitle}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Generated from this course&apos;s chapters. Edits stay in a draft until you publish.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="secondary" onClick={() => setShowUpload((value) => !value)}>
            {showUpload ? "Close upload" : "Upload skill map"}
          </Button>
          {draft && (
            <Button variant="primary" onClick={() => void handlePublish()}>
              Publish skill map
            </Button>
          )}
        </div>
      </div>

      {message && (
        <p role="status" className="rounded-md bg-accent-soft px-4 py-2 text-sm">
          {message}
        </p>
      )}

      {status?.phase === "generating" && (
        <Card className="flex items-center gap-3 py-4">
          <Badge tone="warning">Generating</Badge>
          <p className="text-sm text-muted-foreground">
            Reading your chapters and drafting the skill map… this page updates when it&apos;s ready.
          </p>
        </Card>
      )}

      {status?.phase === "failed" && (
        <Card className="flex items-center gap-3 py-4">
          <Badge tone="serious">Failed</Badge>
          <p className="flex-1 text-sm text-muted-foreground">
            {status.error_code && (
              <span className="font-mono text-xs font-semibold text-status-serious">
                {status.error_code}
              </span>
            )}
            {status.error_code && status.error && <span className="mx-1">·</span>}
            {status.error ?? "Skill map generation failed."}
          </p>
          <Button
            variant="secondary"
            onClick={() => void handleGenerate()}
            disabled={status.locked}
          >
            Regenerate
          </Button>
        </Card>
      )}

      {showUpload && (
        <Card className="flex flex-col gap-3">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-xl font-semibold">Upload a skill map</h2>
            <span className="text-xs text-muted-foreground">max 20 skills</span>
          </div>
          <p className="text-sm text-muted-foreground">
            Paste a skill map generated by another AI. Uploading replaces the current draft;
            publish when you&apos;re happy with it.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="secondary" onClick={() => void handleShowTemplate()}>
              {uploadTemplate ? "Hide example prompt" : "Show example prompt"}
            </Button>
            {uploadTemplate && (
              <Button
                variant="secondary"
                className="inline-flex items-center gap-1.5"
                onClick={() => void handleCopyTemplate()}
              >
                {copied ? <Check className="h-4 w-4" aria-hidden="true" /> : <Copy className="h-4 w-4" aria-hidden="true" />}
                {copied ? "Copied" : "Copy prompt"}
              </Button>
            )}
          </div>
          {uploadTemplate && (
            <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md border border-divider bg-background p-3 text-xs">
              {uploadTemplate}
            </pre>
          )}
          <textarea
            aria-label="Skill map JSON"
            value={uploadJson}
            onChange={(event) => setUploadJson(event.target.value)}
            className="min-h-40 rounded-md border border-divider bg-background px-3 py-2 font-mono text-xs"
            placeholder='{"concepts": [{"label": "...", "description": "...", "introduced_in": "...", "prerequisites": ["..."]}]}'
          />
          <div>
            <Button variant="primary" onClick={() => void handleUpload()} disabled={uploading}>
              {uploading ? "Uploading…" : "Upload skill map"}
            </Button>
          </div>
        </Card>
      )}

      {!draft && status?.phase !== "generating" && (
        <EmptyState
          icon="🧭"
          title={status?.locked ? "Skill map is locked" : "No skill map draft yet"}
          body={
            status?.locked
              ? "You've started learning, so the skill map is locked to protect your progress. You can still edit it manually."
              : "Generate one from this course's chapters, then edit and publish it."
          }
          cta={
            <div className="flex flex-wrap items-center justify-center gap-3">
              {status?.locked ? (
                <Button variant="primary" onClick={() => void handleStartEditing()}>
                  Start editing
                </Button>
              ) : (
                <Button variant="primary" onClick={() => void handleGenerate()}>
                  Generate skill map
                </Button>
              )}
              <Button variant="secondary" onClick={() => setShowUpload(true)}>
                Upload skill map
              </Button>
            </div>
          }
        />
      )}

      {draft && (
        <>
          <SkillMapGraphPreview concepts={draft.concepts} relations={draft.relations} />

          <section className="flex flex-col gap-3">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-semibold">Competencies</h2>
              <span className="text-sm text-muted-foreground">{draft.concepts.length} total</span>
            </div>

            {draft.concepts.map((concept) => {
              const edit = edits[concept.id] ?? {
                label: concept.label,
                description_md: concept.description_md,
                section_id: concept.section_id ?? "",
              };
              return (
                <Card key={concept.id} className="flex flex-col gap-3">
                  <div className="flex items-center justify-between gap-3">
                    <label className="flex-1 text-sm font-semibold">
                      <span className="sr-only">Concept label</span>
                      <input
                        value={edit.label}
                        onChange={(event) =>
                          setEdits((current) => ({
                            ...current,
                            [concept.id]: { ...edit, label: event.target.value },
                          }))
                        }
                        className="w-full rounded-md border border-divider bg-background px-3 py-2 font-semibold"
                      />
                    </label>
                    <Button size="sm" variant="danger" onClick={() => void deleteConcept(concept.id)}>
                      Remove
                    </Button>
                  </div>

                  <textarea
                    aria-label={`Description for ${concept.label}`}
                    value={edit.description_md}
                    onChange={(event) =>
                      setEdits((current) => ({
                        ...current,
                        [concept.id]: { ...edit, description_md: event.target.value },
                      }))
                    }
                    className="min-h-20 rounded-md border border-divider bg-background px-3 py-2 text-sm"
                    placeholder="What does this competency mean?"
                  />

                  <div className="flex flex-wrap items-end gap-3">
                    <label className="flex flex-col gap-1 text-sm">
                      <span className="text-muted-foreground">Introduced in</span>
                      <select
                        value={edit.section_id}
                        onChange={(event) =>
                          setEdits((current) => ({
                            ...current,
                            [concept.id]: { ...edit, section_id: event.target.value },
                          }))
                        }
                        className="min-w-64 rounded-md border border-divider bg-background px-3 py-2"
                      >
                        <option value="">— not linked —</option>
                        {contentSections.map((section) => (
                          <option key={section.id} value={section.id}>
                            {section.chapter_label ? `${section.chapter_label} · ` : ""}
                            {section.title}
                          </option>
                        ))}
                      </select>
                    </label>
                    <Button size="sm" onClick={() => void saveConcept(concept.id)}>
                      Save
                    </Button>
                  </div>
                </Card>
              );
            })}
          </section>

          <Card className="flex flex-col gap-3">
            <h3 className="text-base font-semibold">Add a competency</h3>
            <div className="flex flex-wrap items-end gap-3">
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">Label</span>
                <input
                  value={newLabel}
                  onChange={(event) => setNewLabel(event.target.value)}
                  className="rounded-md border border-divider bg-background px-3 py-2"
                  placeholder="e.g. Fractions"
                />
              </label>
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted-foreground">Key (stable id)</span>
                <input
                  value={newSlug}
                  onChange={(event) => setNewSlug(event.target.value)}
                  className="rounded-md border border-divider bg-background px-3 py-2"
                  placeholder="auto from label"
                />
              </label>
              <Button variant="primary" onClick={() => void handleAddConcept()}>
                Add competency
              </Button>
            </div>
          </Card>

          <section className="flex flex-col gap-3">
            <h2 className="text-xl font-semibold">Prerequisites</h2>
            {edges.length === 0 ? (
              <p className="text-sm text-muted-foreground">No prerequisites yet.</p>
            ) : (
              edges.map((edge) => (
                <Card key={edge.relation_id} className="flex items-center gap-3 py-3">
                  <span className="text-sm font-semibold">
                    {conceptById.get(edge.from)?.label ?? edge.from}
                  </span>
                  <span className="text-muted-foreground">→</span>
                  <span className="flex-1 text-sm font-semibold">
                    {conceptById.get(edge.to)?.label ?? edge.to}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      void run(() => deleteCurriculumRelation(edge.relation_id), "Prerequisite removed.")
                    }
                  >
                    Remove
                  </Button>
                </Card>
              ))
            )}

            <Card className="flex flex-col gap-3">
              <h3 className="text-base font-semibold">Add a prerequisite</h3>
              <div className="flex flex-wrap items-end gap-3">
                <label className="flex flex-col gap-1 text-sm">
                  <span className="text-muted-foreground">Learn first</span>
                  <select
                    value={edgeFrom}
                    onChange={(event) => setEdgeFrom(event.target.value)}
                    className="min-w-56 rounded-md border border-divider bg-background px-3 py-2"
                  >
                    <option value="">—</option>
                    {draft.concepts.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </label>
                <span className="text-muted-foreground">→</span>
                <label className="flex flex-col gap-1 text-sm">
                  <span className="text-muted-foreground">Then learn</span>
                  <select
                    value={edgeTo}
                    onChange={(event) => setEdgeTo(event.target.value)}
                    className="min-w-56 rounded-md border border-divider bg-background px-3 py-2"
                  >
                    <option value="">—</option>
                    {draft.concepts.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.label}
                      </option>
                    ))}
                  </select>
                </label>
                <Button variant="primary" onClick={() => void handleAddEdge()}>
                  Add prerequisite
                </Button>
              </div>
            </Card>
          </section>
        </>
      )}
    </div>
  );
}
