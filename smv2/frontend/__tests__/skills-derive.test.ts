import { describe, expect, it } from "vitest";

import type { SkillEdgeOut, SkillNodeOut } from "@/lib/api/client";
import { blockedBy, describeNode, rootCause, weakestPrereq } from "@/lib/skills/derive";

function node(overrides: Partial<SkillNodeOut> & Pick<SkillNodeOut, "id" | "label">): SkillNodeOut {
  return {
    slug: overrides.id,
    level: 1,
    mastery: 50,
    status: "growing",
    blocked: false,
    unlock_note: null,
    ...overrides,
  };
}

// Same 6-node graph as __tests__/skills-map.test.tsx: token-counting's low
// mastery (31) makes its outgoing edges "weak", which is what makes
// cost-estimation and context-management blocked=true.
const NODES: SkillNodeOut[] = [
  node({ id: "tokenization", label: "Tokenization basics", mastery: 86, status: "solid" }),
  node({ id: "token-counting", label: "Token counting", mastery: 31, status: "struggling" }),
  node({ id: "prompt-structure", label: "Prompt structure", mastery: 58, status: "growing" }),
  node({ id: "cost-estimation", label: "Cost estimation", level: 2, mastery: 24, status: "struggling", blocked: true }),
  node({ id: "context-management", label: "Context management", level: 2, mastery: 52, status: "growing", blocked: true }),
  node({ id: "caching", label: "Prompt caching", level: 3, mastery: 0, status: "locked", blocked: true, unlock_note: "Unlocks at 60 mastery of Cost estimation" }),
];

const EDGES: SkillEdgeOut[] = [
  { from_id: "tokenization", to_id: "token-counting", kind: "met" },
  { from_id: "token-counting", to_id: "cost-estimation", kind: "weak" },
  { from_id: "token-counting", to_id: "context-management", kind: "weak" },
  { from_id: "prompt-structure", to_id: "context-management", kind: "weak" },
  { from_id: "cost-estimation", to_id: "caching", kind: "weak" },
  { from_id: "context-management", to_id: "caching", kind: "weak" },
];

describe("blockedBy", () => {
  it("returns nodes reached via an outgoing WEAK edge only, not every downstream node", () => {
    // tokenization -> token-counting is "met", so tokenization blocks nothing.
    expect(blockedBy(NODES, EDGES, "tokenization")).toEqual([]);
    // token-counting -> cost-estimation and -> context-management are both weak.
    expect(blockedBy(NODES, EDGES, "token-counting").map((n) => n.id)).toEqual([
      "cost-estimation",
      "context-management",
    ]);
  });

  it("returns an empty array for a leaf node with no outgoing edges", () => {
    expect(blockedBy(NODES, EDGES, "caching")).toEqual([]);
  });
});

describe("weakestPrereq", () => {
  it("picks the lowest-mastery incoming weak prerequisite", () => {
    const caching = NODES.find((n) => n.id === "caching")!;
    // Incoming weak: cost-estimation (24), context-management (52) -> weakest is cost-estimation.
    expect(weakestPrereq(caching, NODES, EDGES)?.id).toBe("cost-estimation");
  });

  it("returns null when the node has no incoming weak edge", () => {
    const tokenCounting = NODES.find((n) => n.id === "token-counting")!;
    // Its only incoming edge (from tokenization) is "met", not "weak".
    expect(weakestPrereq(tokenCounting, NODES, EDGES)).toBeNull();
  });

  it("tie-breaks equal mastery by id", () => {
    const a = node({ id: "a", label: "A", mastery: 10 });
    const b = node({ id: "b", label: "B", mastery: 10 });
    const target = node({ id: "target", label: "Target", blocked: true });
    const edges: SkillEdgeOut[] = [
      { from_id: "b", to_id: "target", kind: "weak" },
      { from_id: "a", to_id: "target", kind: "weak" },
    ];
    expect(weakestPrereq(target, [a, b, target], edges)?.id).toBe("a");
  });
});

describe("rootCause", () => {
  it("finds the first struggling+blocked node and its weakest weak prerequisite", () => {
    const cause = rootCause(NODES, EDGES);
    expect(cause?.skill.id).toBe("cost-estimation");
    expect(cause?.prereq.id).toBe("token-counting");
  });

  it("skips a struggling node that isn't blocked (its own low mastery, not a weak prereq)", () => {
    // token-counting is "struggling" but blocked=false in this fixture — it
    // must not be picked, even though it comes first in the array.
    const withoutCostEstimation = NODES.filter((n) => n.id !== "cost-estimation");
    const cause = rootCause(withoutCostEstimation, EDGES);
    expect(cause).toBeNull();
  });

  it("returns null when nothing is both struggling and blocked", () => {
    const allSolid = NODES.map((n) => ({ ...n, status: "solid", blocked: false }));
    expect(rootCause(allSolid, EDGES)).toBeNull();
  });
});

describe("describeNode", () => {
  it("uses unlock_note verbatim for a locked node", () => {
    const caching = NODES.find((n) => n.id === "caching")!;
    expect(describeNode(caching, NODES, EDGES)).toBe("Unlocks at 60 mastery of Cost estimation");
  });

  it("names the weakest prerequisite for a blocked node", () => {
    const costEstimation = NODES.find((n) => n.id === "cost-estimation")!;
    expect(describeNode(costEstimation, NODES, EDGES)).toBe("24 mastery · requires Token counting");
  });

  it("counts how many skills it blocks when it is itself a weak prerequisite (plural)", () => {
    const tokenCounting = NODES.find((n) => n.id === "token-counting")!;
    expect(describeNode(tokenCounting, NODES, EDGES)).toBe("31 mastery · blocks 2 skills");
  });

  it("uses the singular form for exactly one blocked skill", () => {
    const promptStructure = NODES.find((n) => n.id === "prompt-structure")!;
    // prompt-structure -> context-management is its only outgoing edge, and it's weak.
    expect(describeNode(promptStructure, NODES, EDGES)).toBe("58 mastery · blocks 1 skill");
  });

  it("falls back to bare mastery when neither blocked nor blocking anything", () => {
    const tokenization = NODES.find((n) => n.id === "tokenization")!;
    // tokenization's only outgoing edge is "met", not "weak" — blocks nothing.
    expect(describeNode(tokenization, NODES, EDGES)).toBe("86 mastery");
  });
});
