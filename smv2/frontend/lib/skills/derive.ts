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

/** Precomputed per-node lookups `describeNode` needs, built with a single
 * pass over `edges` instead of the `weakestPrereq`/`blockedBy` filter+Map
 * work `describeNode` alone would otherwise repeat once per node. Callers
 * that render `describeNode` for every node in a list (e.g. SkillMapView's
 * `nodes.map`) should build this once outside that loop via
 * `buildSkillDeriveIndex` and call `describeNodeFromIndex` instead — that
 * turns an O(nodes * edges) render into a single O(nodes + edges) pass. */
export interface SkillDeriveIndex {
  weakestPrereqById: Map<string, SkillNodeOut>;
  blockedCountById: Map<string, number>;
}

export function buildSkillDeriveIndex(nodes: SkillNodeOut[], edges: SkillEdgeOut[]): SkillDeriveIndex {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const weakestPrereqById = new Map<string, SkillNodeOut>();
  const blockedCountById = new Map<string, number>();
  for (const edge of edges) {
    if (edge.kind !== "weak") continue;
    // Weakest-prereq candidate for edge.to_id: same min-by-(mastery, id)
    // tie-break as weakestPrereq's reduce, just accumulated in one pass
    // instead of re-filtering `edges` per node.
    const from = byId.get(edge.from_id);
    if (from) {
      const current = weakestPrereqById.get(edge.to_id);
      if (!current || from.mastery < current.mastery || (from.mastery === current.mastery && from.id < current.id)) {
        weakestPrereqById.set(edge.to_id, from);
      }
    }
    // Count of nodes this edge's `from_id` blocks — same "resolved to_id
    // node must exist" guard as blockedBy's own `.filter(n => n !==
    // undefined)`, since describeNode only ever needs the count.
    if (byId.has(edge.to_id)) {
      blockedCountById.set(edge.from_id, (blockedCountById.get(edge.from_id) ?? 0) + 1);
    }
  }
  return { weakestPrereqById, blockedCountById };
}

/** One-line note for a skill map card — the mock's "{mastery} mastery ·
 * {context}" pattern, built only from fields the API actually returns
 * (no per-node blurb exists server-side): unlock_note when locked, else
 * "requires {weakest prereq}" when blocked, else "blocks N skills" when
 * this concept is itself someone else's weak prerequisite, else bare
 * mastery. Takes a `buildSkillDeriveIndex` result rather than raw
 * nodes/edges so a caller rendering this per-node can build that index
 * once and reuse it. */
export function describeNodeFromIndex(node: SkillNodeOut, index: SkillDeriveIndex): string {
  if (node.status === "locked" && node.unlock_note) return node.unlock_note;
  if (node.blocked) {
    const prereq = index.weakestPrereqById.get(node.id);
    return prereq ? `${node.mastery} mastery · requires ${prereq.label}` : `${node.mastery} mastery`;
  }
  const blocks = index.blockedCountById.get(node.id) ?? 0;
  if (blocks > 0) {
    return `${node.mastery} mastery · blocks ${blocks} skill${blocks === 1 ? "" : "s"}`;
  }
  return `${node.mastery} mastery`;
}

/** Convenience wrapper for a single node — builds a one-node-sized index
 * and delegates to `describeNodeFromIndex`. Callers that need this for
 * every node in `nodes` (anything looping over the full list) should use
 * `buildSkillDeriveIndex` + `describeNodeFromIndex` directly instead of
 * calling this in a loop, which would rebuild the index every time. */
export function describeNode(node: SkillNodeOut, nodes: SkillNodeOut[], edges: SkillEdgeOut[]): string {
  return describeNodeFromIndex(node, buildSkillDeriveIndex(nodes, edges));
}
