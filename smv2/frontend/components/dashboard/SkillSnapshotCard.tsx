"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import ProgressBar, { type ProgressBarTone } from "@/components/ui/ProgressBar";
import { rootCause, SAMPLE_DATA_LABEL, SKILL_NODES, type SkillStatus } from "@/lib/skills/placeholder";

export interface SkillSnapshotCardProps {
  /** A course id to scope the "Full map"/"Review the prerequisite" links to. */
  courseId: string;
}

// ProgressBar only exposes 3 tones — growing and struggling both read as
// "accent" (the mock distinguishes them with a mid vs. deep accent shade,
// which the shared primitive doesn't expose).
const BAR_TONES: Record<SkillStatus, ProgressBarTone> = {
  solid: "sage",
  growing: "accent",
  struggling: "accent",
  locked: "neutral",
};

const SCORE_TEXT: Record<SkillStatus, string> = {
  solid: "text-sage-700",
  growing: "text-accent-700",
  struggling: "text-accent-800",
  locked: "text-neutral-600",
};

const SNAPSHOT_COUNT = 3;

/**
 * Home's "Skill snapshot" (redesign handoff §1) — reads from the
 * lib/skills/placeholder sample module until the prereq-graph backend
 * lands (see that module's own doc comment). Must stay visibly tagged as
 * sample data — the Badge below is not decorative.
 */
export default function SkillSnapshotCard({ courseId }: SkillSnapshotCardProps) {
  const router = useRouter();
  const cause = rootCause();
  const snapshot = SKILL_NODES.slice(0, SNAPSHOT_COUNT);

  return (
    <Card className="flex flex-col gap-3.5">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2">
          <span className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
            Skill snapshot
          </span>
          <Badge tone="neutral">{SAMPLE_DATA_LABEL}</Badge>
        </span>
        <Link
          href={`/course/${courseId}/skills`}
          className="text-sm font-medium text-accent-700 hover:underline"
        >
          Full map →
        </Link>
      </div>

      <div className="flex flex-col gap-3">
        {snapshot.map((node) => (
          <div key={node.id}>
            <div className="mb-1.5 flex items-center justify-between text-[13px] font-semibold">
              <span>{node.name}</span>
              <span className={SCORE_TEXT[node.status]}>{node.mastery}</span>
            </div>
            <ProgressBar
              percent={node.mastery}
              label={`${node.name} mastery`}
              tone={BAR_TONES[node.status]}
            />
          </div>
        ))}
      </div>

      {cause && (
        <Card variant="tinted" className="gap-2 text-sm leading-relaxed">
          <p>
            <strong>Why you&apos;re stuck:</strong> {cause.skill.name} builds on{" "}
            <strong>{cause.prereq.name}</strong>. {cause.skill.note}
          </p>
          <Button
            variant="primary"
            size="sm"
            className="self-start"
            onClick={() => router.push(`/course/${courseId}/skills/${cause.prereq.id}`)}
          >
            Review the prerequisite
          </Button>
        </Card>
      )}
    </Card>
  );
}
