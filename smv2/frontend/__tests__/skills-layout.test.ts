import { describe, expect, it } from "vitest";

import type { SkillEdgeOut, SkillNodeOut } from "@/lib/api/client";
import { computeSkillMapLayout, SKILL_CARD_HEIGHT, SKILL_CARD_WIDTH } from "@/components/skills/layout";

function node(overrides: Partial<SkillNodeOut> & Pick<SkillNodeOut, "id" | "label" | "level">): SkillNodeOut {
  return {
    slug: overrides.id,
    status: "insufficient_evidence",
    readiness_estimate: null,
    evidence_state: "insufficient_evidence",
    ...overrides,
  };
}

describe("computeSkillMapLayout", () => {
  it("places a single node in one lane at the top row", () => {
    const solo = node({ id: "solo", label: "Solo", level: 1 });
    const layout = computeSkillMapLayout([solo], []);

    expect(layout.lanes).toEqual([{ level: 1, name: "Level 1 · Foundations", leftPx: 0 }]);
    expect(layout.nodePositions.solo).toEqual({ leftPx: 0, topPx: 30 });
    expect(layout.edges).toEqual([]);
    // One lane, no dividers between lanes.
    expect(layout.dividers).toEqual([]);
    expect(layout.canvasWidth).toBe(SKILL_CARD_WIDTH);
    expect(layout.canvasHeight).toBe(30 + SKILL_CARD_HEIGHT);
  });

  it("gives each node in an unbalanced level its own non-overlapping row", () => {
    const nodes: SkillNodeOut[] = [
      node({ id: "l1-a", label: "L1 A", level: 1 }),
      node({ id: "l2-a", label: "L2 A", level: 2 }),
      node({ id: "l2-b", label: "L2 B", level: 2 }),
      node({ id: "l2-c", label: "L2 C", level: 2 }),
    ];
    const layout = computeSkillMapLayout(nodes, []);

    // Level 1's lone node sits at the top row of its lane.
    expect(layout.nodePositions["l1-a"]).toEqual({ leftPx: 0, topPx: 30 });

    // Level 2's three nodes share a lane (second lane) but get distinct,
    // ascending, non-overlapping rows (array order = row order).
    const laneTwoLeft = layout.nodePositions["l2-a"].leftPx;
    expect(laneTwoLeft).toBeGreaterThan(layout.nodePositions["l1-a"].leftPx);
    expect(layout.nodePositions["l2-b"].leftPx).toBe(laneTwoLeft);
    expect(layout.nodePositions["l2-c"].leftPx).toBe(laneTwoLeft);

    const tops = ["l2-a", "l2-b", "l2-c"].map((id) => layout.nodePositions[id].topPx);
    // Strictly ascending and each pair separated by more than one card's
    // height, i.e. genuinely non-overlapping rows, not identical positions.
    expect(tops[1]).toBeGreaterThan(tops[0]);
    expect(tops[2]).toBeGreaterThan(tops[1]);
    expect(tops[1] - tops[0]).toBeGreaterThanOrEqual(SKILL_CARD_HEIGHT);
    expect(tops[2] - tops[1]).toBeGreaterThanOrEqual(SKILL_CARD_HEIGHT);

    // Canvas height accounts for the taller (3-row) lane, not the 1-row one.
    expect(layout.canvasHeight).toBe(30 + 3 * 170 - (170 - SKILL_CARD_HEIGHT));
  });

  it("fans out three-plus incoming edges on one node into distinct target y-offsets", () => {
    const nodes: SkillNodeOut[] = [
      node({ id: "a", label: "A", level: 1 }),
      node({ id: "b", label: "B", level: 1 }),
      node({ id: "c", label: "C", level: 1 }),
      node({ id: "target", label: "Target", level: 2 }),
    ];
    const edges: SkillEdgeOut[] = [
      { from_id: "a", to_id: "target", kind: "review_suggested" },
      { from_id: "b", to_id: "target", kind: "review_suggested" },
      { from_id: "c", to_id: "target", kind: "ready" },
    ];
    const layout = computeSkillMapLayout(nodes, edges);

    expect(layout.edges).toHaveLength(3);
    const tys = layout.edges.map((e) => e.ty);
    // Sane: every incoming edge on "target" lands on a DIFFERENT y, so the
    // three curves/dots are visibly distinguishable rather than stacked.
    expect(new Set(tys).size).toBe(3);
  });
});
