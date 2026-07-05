/**
 * Pure logic for the outline confirmation screen: tracks the user's local
 * edits (rename/delete/reorder/merge/split) as a draft, separate from
 * React, and translates the draft into the minimal OutlineOp[] to PATCH —
 * or [] if nothing changed, so "Accept as-is" never issues an empty PATCH.
 */

import type { OutlineOp, SectionOut } from "@/lib/api/client";

export interface OutlineDraftState {
  /** Ids of non-deleted sections, in the user's current display order. */
  order: string[];
  renamed: Record<string, string>;
  deleted: Set<string>;
  /** Each entry is 2+ adjacent section ids staged to merge together. */
  merges: string[][];
  splits: Record<string, number>;
}

export function initialDraftState(sections: SectionOut[]): OutlineDraftState {
  return {
    order: [...sections].sort((a, b) => a.order_index - b.order_index).map((section) => section.id),
    renamed: {},
    deleted: new Set(),
    merges: [],
    splits: {},
  };
}

function arraysEqual(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

/**
 * A group can be merged only if its ids are contiguous in the current
 * display order — merging non-adjacent chapters isn't a meaningful edit
 * (there's nothing sensible for the backend to combine them into).
 */
export function isAdjacentGroup(order: string[], ids: string[]): boolean {
  if (ids.length < 2) return false;
  const positions = ids.map((id) => order.indexOf(id)).sort((a, b) => a - b);
  if (positions.some((position) => position === -1)) return false;
  for (let i = 1; i < positions.length; i++) {
    if (positions[i] !== positions[i - 1] + 1) return false;
  }
  return true;
}

export function buildOutlineOps(original: SectionOut[], draft: OutlineDraftState): OutlineOp[] {
  const ops: OutlineOp[] = [];
  const mergedIds = new Set(draft.merges.flat());
  const splitIds = new Set(Object.keys(draft.splits));

  for (const section of original) {
    if (draft.deleted.has(section.id)) {
      ops.push({ type: "delete", section_id: section.id });
    }
  }

  for (const section of original) {
    if (draft.deleted.has(section.id) || mergedIds.has(section.id)) continue;
    const newTitle = draft.renamed[section.id];
    if (newTitle !== undefined && newTitle !== section.title) {
      ops.push({ type: "rename", section_id: section.id, title: newTitle });
    }
  }

  for (const group of draft.merges) {
    ops.push({ type: "merge", section_ids: group });
  }

  for (const [sectionId, atPage] of Object.entries(draft.splits)) {
    ops.push({ type: "split", section_id: sectionId, at_page: atPage });
  }

  // Reorder is scoped to sections untouched by delete/merge/split — their
  // resulting ids after those ops aren't known client-side, so "where do
  // they go in the final order" isn't a meaningful question to ask here.
  const reorderable = draft.order.filter(
    (id) => !draft.deleted.has(id) && !mergedIds.has(id) && !splitIds.has(id),
  );
  const originalOrderOfReorderable = original
    .filter((section) => reorderable.includes(section.id))
    .sort((a, b) => a.order_index - b.order_index)
    .map((section) => section.id);
  if (reorderable.length > 1 && !arraysEqual(reorderable, originalOrderOfReorderable)) {
    ops.push({ type: "reorder", order: reorderable });
  }

  return ops;
}
