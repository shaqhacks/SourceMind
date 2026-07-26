import Link from "next/link";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import { blockedBy, rootCause, SAMPLE_DATA_LABEL } from "@/lib/skills/placeholder";

export interface DiagnosisCardProps {
  courseId: string;
}

/**
 * SAMPLE DATA — see lib/skills/placeholder.ts. The prereq-graph backend
 * doesn't exist yet, so this card reads from the same client-side
 * placeholder module as the Skill Map, visibly tagged as such, and does
 * not attempt to relate the sample skill graph to this specific course's
 * real test misses.
 */
export default function DiagnosisCard({ courseId }: DiagnosisCardProps) {
  const diagnosis = rootCause();

  return (
    <Card className="flex flex-col gap-3 p-5">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-accent-800">
          Diagnosis
        </span>
        <Badge tone="neutral">{SAMPLE_DATA_LABEL}</Badge>
      </div>
      {diagnosis ? (
        <>
          <p className="text-sm leading-relaxed">
            Misses cluster on <strong>{diagnosis.prereq.name}</strong>. It underpins{" "}
            {blockedBy(diagnosis.prereq.id).length} other skill
            {blockedBy(diagnosis.prereq.id).length === 1 ? "" : "s"} — drilling it now should lift
            your other scores too.
          </p>
          <Link href={`/course/${courseId}/skills/${diagnosis.prereq.id}`}>
            <Button variant="primary" size="sm" className="self-start">
              Drill {diagnosis.prereq.name}
            </Button>
          </Link>
        </>
      ) : (
        <p className="text-sm text-muted-foreground">No diagnosis available right now.</p>
      )}
    </Card>
  );
}
