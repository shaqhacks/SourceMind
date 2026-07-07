"use client";

import { useMemo, useState } from "react";

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
}

/**
 * One skippable screen: "Accept outline" (or plain Enter) is always
 * available and applies whatever's currently staged — including nothing,
 * which is exactly "accept as-is". Edits are staged locally and only sent
 * as a single edit_outline PATCH on accept.
 */
export default function OutlineConfirmation({
  sections,
  onAccept,
  heading = "Confirm chapter outline",
  description = "Review the detected chapters, or accept as-is.",
  submitLabel = "Accept outline",
}: OutlineConfirmationProps) {
  const [draft, setDraft] = useState<OutlineDraftState>(() => initialDraftState(sections));
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [splitInputs, setSplitInputs] = useState<Record<string, string>>({});
  const [editingId, setEditingId] = useState<string | null>(null);

  const byId = useMemo(() => new Map(sections.map((section) => [section.id, section])), [sections]);
  const mergedIds = useMemo(() => new Set(draft.merges.flat()), [draft.merges]);
  const splitIds = useMemo(() => new Set(Object.keys(draft.splits)), [draft.splits]);
  const visibleOrder = draft.order.filter((id) => !draft.deleted.has(id));
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

  function splitSection(id: string) {
    const atPage = Number(splitInputs[id]);
    if (!Number.isInteger(atPage) || atPage <= 0) return;
    setDraft((prev) => ({ ...prev, splits: { ...prev.splits, [id]: atPage } }));
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-base font-semibold">{heading}</h2>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>

      <ul className="divide-y divide-border rounded-md border border-border">
        {visibleOrder.map((id, index) => {
          const section = byId.get(id);
          if (!section) return null;
          const title = draft.renamed[id] ?? section.title;
          const disabled = mergedIds.has(id) || splitIds.has(id);

          return (
            <li key={id} className="flex flex-col gap-2 px-4 py-3">
              <div className="flex items-center gap-3">
                <input
                  type="checkbox"
                  aria-label={`Select ${title}`}
                  checked={selected.has(id)}
                  disabled={disabled}
                  onChange={() => toggleSelected(id)}
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
                    className="flex-1 rounded border border-border px-2 py-1 text-sm"
                  />
                ) : (
                  <button
                    type="button"
                    onClick={() => setEditingId(id)}
                    disabled={disabled}
                    className="flex-1 text-left text-sm font-medium"
                  >
                    {title}
                  </button>
                )}
                {section.page_start !== null && section.page_end !== null ? (
                  <span className="text-xs text-muted-foreground">
                    p.{section.page_start}–{section.page_end}
                  </span>
                ) : null}
                <button
                  type="button"
                  onClick={() => moveUp(id)}
                  disabled={disabled || index === 0}
                  aria-label={`Move ${title} up`}
                >
                  ↑
                </button>
                <button
                  type="button"
                  onClick={() => moveDown(id)}
                  disabled={disabled || index === visibleOrder.length - 1}
                  aria-label={`Move ${title} down`}
                >
                  ↓
                </button>
                <Button variant="danger" size="sm" onClick={() => remove(id)} disabled={disabled}>
                  Delete
                </Button>
              </div>

              {mergedIds.has(id) && (
                <p className="text-xs text-muted-foreground">
                  Will merge with the adjacent selected chapters.
                </p>
              )}
              {splitIds.has(id) && (
                <p className="text-xs text-muted-foreground">
                  Will split at page {draft.splits[id]}.
                </p>
              )}
              {!disabled && (
                <div className="flex items-center gap-2">
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
                    className="w-20 rounded border border-border px-2 py-1 text-sm"
                  />
                  <button
                    type="button"
                    onClick={() => splitSection(id)}
                    className="text-xs font-medium text-accent"
                  >
                    Split
                  </button>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      {selected.size >= 2 && (
        <div className="flex items-center gap-3 rounded-md border border-border p-3">
          <button
            type="button"
            onClick={mergeSelected}
            disabled={!canMerge}
            className="text-sm font-medium text-accent disabled:opacity-50"
          >
            Merge selected
          </button>
          {!canMerge && (
            <p className="text-xs text-muted-foreground">Only adjacent chapters can be merged.</p>
          )}
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Merging or splitting resets review state for the affected chapters.
      </p>

      <div className="flex justify-end">
        <Button variant="primary" onClick={handleAccept}>
          {submitLabel}
        </Button>
      </div>
    </div>
  );
}
