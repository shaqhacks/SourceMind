"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import type { OutlineOp, SectionOut } from "@/lib/api/client";
import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";
import {
  buildOutlineOps,
  initialDraftState,
  isAdjacentGroup,
  type OutlineDraftState,
} from "@/lib/upload/outlineOps";

export interface OutlineConfirmationProps {
  sections: SectionOut[];
  onAccept: (operations: OutlineOp[]) => void;
  /** Overridable copy so this same editor reads naturally in both of its
   * homes: the upload flow's first-look confirmation (defaults below) and
   * the reader's "Edit outline" modal (which passes its own wording). */
  heading?: string;
  description?: string;
  submitLabel?: string;
  reassuranceNote?: string;
  /** Renders a secondary Cancel button beside submit — the New Course
   * dialog's step 2 wants both actions together; the reader's Edit Outline
   * modal supplies its own Close button instead and omits this. */
  onCancel?: () => void;
  cancelLabel?: string;
}

/**
 * One skippable screen: "Accept outline" (or plain Enter) is always
 * available and applies whatever's currently staged — including nothing,
 * which is exactly "accept as-is". Edits are staged locally and only sent
 * as a single edit_outline PATCH on accept.
 *
 * A staged merge collapses to a single row (the group's first chapter,
 * tinted, carrying a "merging with N" badge referencing the other
 * chapters' original bookmark numbers) rather than showing every merged
 * row disabled — Undo un-stages the whole group. Row numbers reflect the
 * user's live display order, so numbering stays sequential even as
 * merged rows disappear.
 */
export default function OutlineConfirmation({
  sections,
  onAccept,
  heading = "Confirm chapter outline",
  description = "Review the detected chapters, or accept as-is.",
  submitLabel = "Accept outline",
  reassuranceNote = "Merging or splitting resets review state for the affected chapters.",
  onCancel,
  cancelLabel = "Cancel",
}: OutlineConfirmationProps) {
  const [draft, setDraft] = useState<OutlineDraftState>(() => initialDraftState(sections));
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [splitInputs, setSplitInputs] = useState<Record<string, string>>({});
  const [editingId, setEditingId] = useState<string | null>(null);
  const [splitOpenId, setSplitOpenId] = useState<string | null>(null);

  const byId = useMemo(() => new Map(sections.map((section) => [section.id, section])), [sections]);
  // Each id's fixed original position (1-indexed, by order_index) — stays
  // put across local reorders so a merge badge can reference "the chapter
  // you saw as #4", a number that won't itself shift underneath it.
  const originalNumber = useMemo(() => {
    const sorted = [...sections].sort((a, b) => a.order_index - b.order_index);
    return new Map(sorted.map((section, index) => [section.id, index + 1]));
  }, [sections]);

  const mergedIds = useMemo(() => new Set(draft.merges.flat()), [draft.merges]);
  // Only a merge group's first id renders a row; this maps that id to the
  // other members' original numbers for its "merging with N" badge.
  const mergePartners = useMemo(() => {
    const map = new Map<string, number[]>();
    for (const group of draft.merges) {
      const [first, ...rest] = group;
      map.set(
        first,
        rest.map((id) => originalNumber.get(id)).filter((n): n is number => n !== undefined),
      );
    }
    return map;
  }, [draft.merges, originalNumber]);
  const hiddenMergeMembers = useMemo(
    () => new Set(draft.merges.flatMap((group) => group.slice(1))),
    [draft.merges],
  );
  const splitIds = useMemo(() => new Set(Object.keys(draft.splits)), [draft.splits]);
  const visibleOrder = draft.order.filter(
    (id) => !draft.deleted.has(id) && !hiddenMergeMembers.has(id),
  );
  const selectedInOrder = visibleOrder.filter((id) => selected.has(id));
  const canMerge = selected.size >= 2 && isAdjacentGroup(visibleOrder, selectedInOrder);

  function handleAccept() {
    onAccept(buildOutlineOps(sections, draft));
  }

  useKeyboardShortcuts({ enter: handleAccept });

  function moveUp(id: string) {
    setDraft((prev) => {
      const index = prev.order.indexOf(id);
      if (index <= 0) return prev;
      const order = [...prev.order];
      [order[index - 1], order[index]] = [order[index], order[index - 1]];
      return { ...prev, order };
    });
  }

  function moveDown(id: string) {
    setDraft((prev) => {
      const index = prev.order.indexOf(id);
      if (index === -1 || index >= prev.order.length - 1) return prev;
      const order = [...prev.order];
      [order[index], order[index + 1]] = [order[index + 1], order[index]];
      return { ...prev, order };
    });
  }

  function rename(id: string, title: string) {
    setDraft((prev) => ({ ...prev, renamed: { ...prev.renamed, [id]: title } }));
  }

  function remove(id: string) {
    setDraft((prev) => {
      const deleted = new Set(prev.deleted);
      deleted.add(id);
      return { ...prev, deleted };
    });
    setSelected((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }

  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function mergeSelected() {
    if (!canMerge) return;
    setDraft((prev) => ({ ...prev, merges: [...prev.merges, selectedInOrder] }));
    setSelected(new Set());
  }

  function undoMerge(id: string) {
    setDraft((prev) => ({ ...prev, merges: prev.merges.filter((group) => group[0] !== id) }));
  }

  function splitSection(id: string) {
    const atPage = Number(splitInputs[id]);
    if (!Number.isInteger(atPage) || atPage <= 0) return;
    setDraft((prev) => ({ ...prev, splits: { ...prev.splits, [id]: atPage } }));
  }

  function undoSplit(id: string) {
    setDraft((prev) => {
      const splits = { ...prev.splits };
      delete splits[id];
      return { ...prev, splits };
    });
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold">{heading}</h2>
        <p className="shrink-0 text-xs text-muted-foreground">{description}</p>
      </div>

      <ul className="max-h-60 divide-y divide-divider overflow-y-auto rounded-lg border border-divider">
        {visibleOrder.map((id, index) => {
          const section = byId.get(id);
          if (!section) return null;
          const title = draft.renamed[id] ?? section.title;
          const displayNumber = index + 1;
          const isMergeHead = mergedIds.has(id);
          const isSplitStaged = splitIds.has(id);
          const disabled = isMergeHead || isSplitStaged;

          if (isMergeHead) {
            const partners = mergePartners.get(id) ?? [];
            return (
              <li key={id} className="flex items-center gap-3 bg-accent-soft px-3.5 py-2.5 text-sm">
                <span className="flex-1 font-medium">
                  <span aria-hidden="true" className="text-muted-foreground">
                    {displayNumber} ·{" "}
                  </span>
                  {title}
                </span>
                {partners.length > 0 && (
                  <Badge tone="accent">merging with {partners.join(", ")}</Badge>
                )}
                <Button variant="ghost" size="sm" onClick={() => undoMerge(id)}>
                  Undo
                </Button>
              </li>
            );
          }

          return (
            <li key={id} className="flex flex-col gap-2 px-3.5 py-2.5 text-sm">
              <div className="flex items-center gap-3">
                <input
                  type="checkbox"
                  aria-label={`Select ${title}`}
                  checked={selected.has(id)}
                  disabled={disabled}
                  onChange={() => toggleSelected(id)}
                  className="h-4 w-4"
                />
                {editingId === id ? (
                  <input
                    type="text"
                    aria-label={`Rename ${section.title}`}
                    value={title}
                    autoFocus
                    onChange={(event) => rename(id, event.target.value)}
                    onBlur={() => setEditingId(null)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") setEditingId(null);
                    }}
                    className="flex-1 rounded-md border border-border bg-surface-raised px-2 py-1 text-sm focus-visible:border-accent"
                  />
                ) : (
                  <button
                    type="button"
                    onClick={() => setEditingId(id)}
                    disabled={disabled}
                    className="flex-1 text-left font-medium"
                  >
                    <span aria-hidden="true" className="text-muted-foreground">
                      {displayNumber} ·{" "}
                    </span>
                    {title}
                  </button>
                )}
                {section.page_start !== null && section.page_end !== null ? (
                  <span className="shrink-0 text-xs text-muted-foreground">
                    p.{section.page_start}–{section.page_end}
                  </span>
                ) : null}
                {editingId !== id && (
                  <Button variant="ghost" size="sm" onClick={() => setEditingId(id)} disabled={disabled}>
                    Rename
                  </Button>
                )}
                {section.page_start !== null &&
                  section.page_end !== null &&
                  !isSplitStaged &&
                  splitOpenId !== id && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setSplitOpenId(id)}
                    disabled={disabled}
                  >
                    Split
                  </Button>
                )}
                <button
                  type="button"
                  onClick={() => moveUp(id)}
                  disabled={disabled || index === 0}
                  aria-label={`Move ${title} up`}
                  className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-foreground/[0.07] disabled:opacity-40"
                >
                  <ChevronUp className="h-4 w-4" strokeWidth={2.75} />
                </button>
                <button
                  type="button"
                  onClick={() => moveDown(id)}
                  disabled={disabled || index === visibleOrder.length - 1}
                  aria-label={`Move ${title} down`}
                  className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-foreground/[0.07] disabled:opacity-40"
                >
                  <ChevronDown className="h-4 w-4" strokeWidth={2.75} />
                </button>
                <Button variant="danger" size="sm" onClick={() => remove(id)} disabled={disabled}>
                  Delete
                </Button>
              </div>

              {isSplitStaged && (
                <div className="flex items-center gap-2 pl-7">
                  <p className="text-xs text-muted-foreground">
                    Will split at page {draft.splits[id]}.
                  </p>
                  <Button variant="ghost" size="sm" onClick={() => undoSplit(id)}>
                    Undo
                  </Button>
                </div>
              )}

              {!disabled && splitOpenId === id && (
                <div className="flex items-center gap-2 pl-7">
                  <label className="text-xs text-muted-foreground" htmlFor={`split-page-${id}`}>
                    Split at page
                  </label>
                  <input
                    id={`split-page-${id}`}
                    type="number"
                    aria-label={`Split page for ${title}`}
                    value={splitInputs[id] ?? ""}
                    onChange={(event) =>
                      setSplitInputs((prev) => ({ ...prev, [id]: event.target.value }))
                    }
                    className="w-20 rounded-md border border-border bg-surface-raised px-2 py-1 text-sm focus-visible:border-accent"
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      splitSection(id);
                      setSplitOpenId(null);
                    }}
                  >
                    Split
                  </Button>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      {selected.size >= 2 && (
        <div className="flex items-center gap-3 rounded-lg border border-divider p-3">
          <Button variant="ghost" size="sm" onClick={mergeSelected} disabled={!canMerge}>
            Merge selected
          </Button>
          {!canMerge && (
            <p className="text-xs text-muted-foreground">Only adjacent chapters can be merged.</p>
          )}
        </div>
      )}
      <p className="text-xs text-muted-foreground">{reassuranceNote}</p>

      <div className="flex justify-end gap-3">
        {onCancel && (
          <Button variant="secondary" onClick={onCancel}>
            {cancelLabel}
          </Button>
        )}
        <Button variant="primary" onClick={handleAccept}>
          {submitLabel}
        </Button>
      </div>
    </div>
  );
}
