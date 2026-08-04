import { describe, expect, it } from "vitest";

import type { SkillNodeOut } from "@/lib/api/client";
import { describeNode, mostNeedsReview } from "@/lib/skills/derive";

function node(overrides: Partial<SkillNodeOut> & Pick<SkillNodeOut, "id" | "label">): SkillNodeOut {
  return {
    slug: overrides.id,
    level: 1,
    status: "insufficient_evidence",
    readiness_estimate: null,
    evidence_state: "insufficient_evidence",
    distinct_item_count: 0,
    ...overrides,
  };
}

describe("mostNeedsReview", () => {
  it("prioritizes evidence state, then lower readiness", () => {
    const nodes = [
      node({ id: "retained", label: "Retained", status: "retained", evidence_state: "retained", readiness_estimate: 0.8 }),
      node({ id: "building", label: "Building", status: "building", evidence_state: "building", readiness_estimate: 0.2 }),
      node({ id: "struggling-high", label: "Struggling high", status: "likely_struggling", evidence_state: "likely_struggling", readiness_estimate: 0.4 }),
      node({ id: "struggling-low", label: "Struggling low", status: "likely_struggling", evidence_state: "likely_struggling", readiness_estimate: 0.25 }),
    ];
    expect(mostNeedsReview(nodes)?.id).toBe("struggling-low");
  });

  it("does not recommend a concept without an estimate", () => {
    expect(mostNeedsReview([node({ id: "pending", label: "Pending" })])).toBeNull();
  });
});

describe("describeNode", () => {
  it("reports readiness and distinct evidence count", () => {
    expect(
      describeNode(
        node({
          id: "counting",
          label: "Counting",
          readiness_estimate: 0.31,
          distinct_item_count: 5,
        }),
      ),
    ).toBe("31% readiness · 5 evidence items");
  });

  it("keeps missing evidence explicit", () => {
    expect(describeNode(node({ id: "pending", label: "Pending" }))).toBe(
      "Needs more varied evidence",
    );
  });
});
