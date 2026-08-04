import Link from "next/link";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import { useSkillMap } from "@/lib/hooks/useSkillMap";
import { mostNeedsReview } from "@/lib/skills/derive";

export interface DiagnosisCardProps {
  courseId: string;
}

/**
 * Reads the real competency graph via useSkillMap. Renders nothing while
 * loading, on error, or when the course has no skill graph yet (matches
 * ReviewCard's own zero-due hide), same as SkillSnapshotCard.
 */
export default function DiagnosisCard({ courseId }: DiagnosisCardProps) {
  const { map, error } = useSkillMap(courseId);

  if (error || map === null || map.nodes.length === 0) return null;

  const { nodes } = map;
  const reviewTarget = mostNeedsReview(nodes);

  return (
    <Card className="flex flex-col gap-3 p-5">
      <span className="text-xs font-semibold uppercase tracking-wide text-accent-800">
        Learning signal
      </span>
      {reviewTarget ? (
        <>
          <p className="text-sm leading-relaxed">
            Your quiz and review history suggests more practice on{" "}
            <strong>{reviewTarget.label}</strong>. This estimate may change as you answer varied items.
          </p>
          <Link href={`/course/${courseId}/skills/${reviewTarget.id}`}>
            <Button variant="primary" size="sm" className="self-start">
              Review {reviewTarget.label}
            </Button>
          </Link>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">More evidence is needed before suggesting a concept.</p>
      )}
    </Card>
  );
}
