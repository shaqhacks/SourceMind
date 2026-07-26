import type { SkillEdgeOut, SkillNodeOut } from "@/lib/api/client";

/**
 * Client-side derivations over a course's SkillMapOut (nodes/edges) —
 * mirrors the tie-breaks the backend already applies per-concept
 * (app/services/skills_service.py's `build_map`) so the map/snapshot/
 * diagnosis surfaces agree with the detail endpoint's own `fix_plan`
 * without re-deriving mastery/status/levels client-side.
 */

export interface RootCause {
  skill: SkillNodeOut;
  prereq: SkillNodeOut;
}

/** Nodes this concept directly blocks — those it points at via a "weak"
 * edge (mirrors the backend's `blocked_skill_labels`: outgoing weak
 * edges from the concept, not "everything that lists it as a prereq"). */
export function blockedBy(nodes: SkillNodeOut[], edges: SkillEdgeOut[], id: string): SkillNodeOut[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return edges
    .filter((e) => e.from_id === id && e.kind === "weak")
    .map((e) => byId.get(e.to_id))
    .filter((n): n is SkillNodeOut => n !== undefined);
}

/** The weakest incoming "weak" prerequisite of a node — lowest mastery,
 * tie-broken by id — or null when the node has no weak prerequisite.
 * Same tie-break as `weakest_prereq_by_concept` server-side. */
export function weakestPrereq(
  node: SkillNodeOut,
  nodes: SkillNodeOut[],
  edges: SkillEdgeOut[],
): SkillNodeOut | null {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const candidates = edges
    .filter((e) => e.to_id === node.id && e.kind === "weak")
    .map((e) => byId.get(e.from_id))
    .filter((n): n is SkillNodeOut => n !== undefined);
  if (candidates.length === 0) return null;
  return candidates.reduce((a, b) =>
    b.mastery < a.mastery || (b.mastery === a.mastery && b.id < a.id) ? b : a,
  );
}

/** The first struggling-and-blocked skill (in map order) and its weakest
 * prerequisite — drives Home's "Why you're stuck" callout, the Tests
 * page's Diagnosis card, and the map's "Recommended fix" card. Returns
 * null when nothing is both struggling and blocked right now. */
export function rootCause(nodes: SkillNodeOut[], edges: SkillEdgeOut[]): RootCause | null {
  for (const node of nodes) {
    if (node.status !== "struggling" || !node.blocked) continue;
    const prereq = weakestPrereq(node, nodes, edges);
    if (prereq) return { skill: node, prereq };
  }
  return null;
}

/** One-line note for a skill map card — the mock's "{mastery} mastery ·
 * {context}" pattern, built only from fields the API actually returns
 * (no per-node blurb exists server-side): unlock_note when locked, else
 * "requires {weakest prereq}" when blocked, else "blocks N skills" when
 * this concept is itself someone else's weak prerequisite, else bare
 * mastery. */
export function describeNode(node: SkillNodeOut, nodes: SkillNodeOut[], edges: SkillEdgeOut[]): string {
  if (node.status === "locked" && node.unlock_note) return node.unlock_note;
  if (node.blocked) {
    const prereq = weakestPrereq(node, nodes, edges);
    return prereq ? `${node.mastery} mastery · requires ${prereq.label}` : `${node.mastery} mastery`;
  }
  const blocks = blockedBy(nodes, edges, node.id);
  if (blocks.length > 0) {
    return `${node.mastery} mastery · blocks ${blocks.length} skill${blocks.length === 1 ? "" : "s"}`;
  }
  return `${node.mastery} mastery`;
}
