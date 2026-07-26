import Link from "next/link";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import { useSkillMap } from "@/lib/hooks/useSkillMap";
import { blockedBy, rootCause } from "@/lib/skills/derive";

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

  const { nodes, edges } = map;
  const diagnosis = rootCause(nodes, edges);
  const blocksCount = diagnosis ? blockedBy(nodes, edges, diagnosis.prereq.id).length : 0;

  return (
    <Card className="flex flex-col gap-3 p-5">
      <span className="text-xs font-semibold uppercase tracking-wide text-accent-800">
        Diagnosis
      </span>
      {diagnosis ? (
        <>
          <p className="text-sm leading-relaxed">
            Misses cluster on <strong>{diagnosis.prereq.label}</strong>. It underpins{" "}
            {blocksCount} other skill{blocksCount === 1 ? "" : "s"} — drilling it now should lift
            your other scores too.
          </p>
          <Link href={`/course/${courseId}/skills/${diagnosis.prereq.id}`}>
            <Button variant="primary" size="sm" className="self-start">
              Drill {diagnosis.prereq.label}
            </Button>
          </Link>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">No diagnosis available right now.</p>
      )}
    </Card>
  );
}
