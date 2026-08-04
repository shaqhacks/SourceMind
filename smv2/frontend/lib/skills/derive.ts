import type { SkillNodeOut } from "@/lib/api/client";

const REVIEW_PRIORITY: Record<string, number> = {
  likely_struggling: 3,
  building: 2,
  watch: 1,
  retained: 0,
};

export function mostNeedsReview(nodes: SkillNodeOut[]): SkillNodeOut | null {
  const candidates = nodes.filter(
    (node) => node.readiness_estimate != null && node.evidence_state !== "insufficient_evidence",
  );
  return (
    [...candidates].sort((a, b) => {
      const statusDelta =
        (REVIEW_PRIORITY[b.evidence_state ?? ""] ?? 0) -
        (REVIEW_PRIORITY[a.evidence_state ?? ""] ?? 0);
      if (statusDelta !== 0) return statusDelta;
      return (
        (a.readiness_estimate ?? 1) - (b.readiness_estimate ?? 1) ||
        a.id.localeCompare(b.id)
      );
    })[0] ?? null
  );
}

export function describeNode(node: SkillNodeOut): string {
  if (node.readiness_estimate == null) return "Needs more varied evidence";
  const count = node.distinct_item_count ?? 0;
  return `${Math.round(node.readiness_estimate * 100)}% readiness · ${count} evidence item${count === 1 ? "" : "s"}`;
}
