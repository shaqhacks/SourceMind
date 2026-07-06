import { describe, expect, it } from "vitest";

import type { SectionOut } from "@/lib/api/client";
import {
  buildOutlineOps,
  initialDraftState,
  isAdjacentGroup,
} from "@/lib/upload/outlineOps";

function makeSection(overrides: Partial<SectionOut> = {}): SectionOut {
  return {
    id: "sec-1",
    title: "Chapter",
    order_index: 0,
    page_start: 1,
    page_end: 10,
    lesson_status: "none",
    has_content: true,
    word_count: 100,
    kind: "content",
    asset_id: null,
    chapter_label: null,
    ...overrides,
  };
}

const SECTIONS: SectionOut[] = [
  makeSection({ id: "sec-1", title: "Intro", order_index: 0, page_start: 1, page_end: 5 }),
  makeSection({ id: "sec-2", title: "Middle", order_index: 1, page_start: 6, page_end: 10 }),
  makeSection({ id: "sec-3", title: "End", order_index: 2, page_start: 11, page_end: 15 }),
];

describe("initialDraftState", () => {
  it("orders ids by order_index with no edits staged", () => {
    const draft = initialDraftState(SECTIONS);
    expect(draft.order).toEqual(["sec-1", "sec-2", "sec-3"]);
    expect(draft.renamed).toEqual({});
    expect(draft.deleted.size).toBe(0);
    expect(draft.merges).toEqual([]);
    expect(draft.splits).toEqual({});
  });
});

describe("buildOutlineOps", () => {
  it("returns no operations when nothing changed (accept as-is)", () => {
    const draft = initialDraftState(SECTIONS);
    expect(buildOutlineOps(SECTIONS, draft)).toEqual([]);
  });

  it("issues a rename op only for a section whose title actually changed", () => {
    const draft = initialDraftState(SECTIONS);
    draft.renamed["sec-2"] = "Middle Chapter";
    draft.renamed["sec-1"] = "Intro"; // unchanged — same as original title

    const ops = buildOutlineOps(SECTIONS, draft);

    expect(ops).toEqual([{ type: "rename", section_id: "sec-2", title: "Middle Chapter" }]);
  });

  it("issues a delete op per deleted section and excludes it from rename/reorder", () => {
    const draft = initialDraftState(SECTIONS);
    draft.deleted.add("sec-2");
    draft.renamed["sec-2"] = "Should be ignored";

    const ops = buildOutlineOps(SECTIONS, draft);

    expect(ops).toEqual([{ type: "delete", section_id: "sec-2" }]);
  });

  it("issues a merge op for a staged adjacent group", () => {
    const draft = initialDraftState(SECTIONS);
    draft.merges = [["sec-1", "sec-2"]];

    const ops = buildOutlineOps(SECTIONS, draft);

    expect(ops).toEqual([{ type: "merge", section_ids: ["sec-1", "sec-2"] }]);
  });

  it("issues a split op with the chosen page", () => {
    const draft = initialDraftState(SECTIONS);
    draft.splits["sec-3"] = 13;

    const ops = buildOutlineOps(SECTIONS, draft);

    expect(ops).toEqual([{ type: "split", section_id: "sec-3", at_page: 13 }]);
  });

  it("issues a reorder op only when the surviving order actually differs from the original", () => {
    const draft = initialDraftState(SECTIONS);
    draft.order = ["sec-3", "sec-1", "sec-2"];

    const ops = buildOutlineOps(SECTIONS, draft);

    expect(ops).toEqual([{ type: "reorder", order: ["sec-3", "sec-1", "sec-2"] }]);
  });

  it("excludes merged/split sections from the reorder op's candidate set", () => {
    const draft = initialDraftState(SECTIONS);
    draft.merges = [["sec-1", "sec-2"]];
    draft.order = ["sec-3", "sec-1", "sec-2"]; // sec-3 moved to the front

    const ops = buildOutlineOps(SECTIONS, draft);

    // Only sec-3 is reorderable (sec-1/sec-2 are merging away); a single
    // remaining id is never a meaningful reorder.
    expect(ops.find((op) => op.type === "reorder")).toBeUndefined();
    expect(ops).toContainEqual({ type: "merge", section_ids: ["sec-1", "sec-2"] });
  });

  it("combines rename, delete, merge, split, and reorder into one bundle, in that order", () => {
    const draft = initialDraftState(SECTIONS);
    draft.renamed["sec-1"] = "Renamed Intro";
    draft.deleted.add("sec-3");
    // sec-3 is deleted, so only sec-1/sec-2 remain; reorder them.
    draft.order = ["sec-2", "sec-1", "sec-3"];

    const ops = buildOutlineOps(SECTIONS, draft);

    expect(ops).toEqual([
      { type: "delete", section_id: "sec-3" },
      { type: "rename", section_id: "sec-1", title: "Renamed Intro" },
      { type: "reorder", order: ["sec-2", "sec-1"] },
    ]);
  });
});

describe("isAdjacentGroup", () => {
  const order = ["sec-1", "sec-2", "sec-3"];

  it("is false for fewer than 2 ids", () => {
    expect(isAdjacentGroup(order, ["sec-1"])).toBe(false);
    expect(isAdjacentGroup(order, [])).toBe(false);
  });

  it("is true for a contiguous run, regardless of input order", () => {
    expect(isAdjacentGroup(order, ["sec-1", "sec-2"])).toBe(true);
    expect(isAdjacentGroup(order, ["sec-2", "sec-1"])).toBe(true);
    expect(isAdjacentGroup(order, ["sec-1", "sec-2", "sec-3"])).toBe(true);
  });

  it("is false for a non-contiguous selection", () => {
    expect(isAdjacentGroup(order, ["sec-1", "sec-3"])).toBe(false);
  });

  it("is false if an id isn't present in the order at all", () => {
    expect(isAdjacentGroup(order, ["sec-1", "sec-does-not-exist"])).toBe(false);
  });
});
