"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import type { SkillStatus } from "@/components/skills/format";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import ProgressBar, { type ProgressBarTone } from "@/components/ui/ProgressBar";
import { useSkillMap } from "@/lib/hooks/useSkillMap";
import { describeNode, mostNeedsReview } from "@/lib/skills/derive";

export interface SkillSnapshotCardProps {
  /** A course id to scope the "Full map"/"Review the prerequisite" links to. */
  courseId: string;
}

// ProgressBar only exposes 3 tones — growing and struggling both read as
// "accent" (the mock distinguishes them with a mid vs. deep accent shade,
// which the shared primitive doesn't expose).
const BAR_TONES: Record<SkillStatus, ProgressBarTone> = {
  retained: "sage",
  watch: "neutral",
  building: "accent",
  likely_struggling: "accent",
  insufficient_evidence: "neutral",
};

const SCORE_TEXT: Record<SkillStatus, string> = {
  retained: "text-sage-700",
  watch: "text-neutral-700",
  building: "text-accent-700",
  likely_struggling: "text-accent-800",
  insufficient_evidence: "text-neutral-600",
};

const SNAPSHOT_COUNT = 3;

/**
 * Home's "Skill snapshot" (redesign handoff §1) — reads the real
 * competency graph via useSkillMap. Renders nothing while loading, on
 * error, or when the course has no skill graph yet (matches ReviewCard's
 * own zero-due hide), same as DiagnosisCard.
 */
export default function SkillSnapshotCard({ courseId }: SkillSnapshotCardProps) {
  const router = useRouter();
  const { map, error } = useSkillMap(courseId);

  if (error || map === null || map.nodes.length === 0) return null;

  const { nodes } = map;
  const reviewTarget = mostNeedsReview(nodes);
  const snapshot = nodes.slice(0, SNAPSHOT_COUNT);

  return (
    <Card className="flex flex-col gap-3.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
          Skill snapshot
        </span>
        <Link
          href={`/course/${courseId}/skills`}
          className="text-sm font-medium text-accent-700 hover:underline"
        >
          Full map →
        </Link>
      </div>

      <div className="flex flex-col gap-3">
        {snapshot.map((node) => {
          const status = node.status as SkillStatus;
          return (
            <div key={node.id}>
              <div className="mb-1.5 flex items-center justify-between text-[13px] font-semibold">
                <span>{node.label}</span>
                <span className={SCORE_TEXT[status]}>
                  {node.readiness_estimate == null ? "—" : Math.round(node.readiness_estimate * 100)}
                </span>
              </div>
              {node.readiness_estimate == null ? (
                <p className="text-xs text-muted-foreground">Needs more evidence</p>
              ) : (
                <ProgressBar percent={Math.round(node.readiness_estimate * 100)} label={`${node.label} readiness`} tone={BAR_TONES[status]} />
              )}
            </div>
          );
        })}
      </div>

      {reviewTarget && (
        <Card variant="tinted" className="gap-2 text-sm leading-relaxed">
          <p>
            <strong>Suggested review:</strong> Current answer evidence points to{" "}
            <strong>{reviewTarget.label}</strong>. {describeNode(reviewTarget)}
          </p>
          <Button
            variant="primary"
            size="sm"
            className="self-start"
            onClick={() => router.push(`/course/${courseId}/skills/${reviewTarget.id}`)}
          >
            Review the evidence
          </Button>
        </Card>
      )}
    </Card>
  );
}
