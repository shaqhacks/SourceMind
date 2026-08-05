import Badge from "@/components/ui/Badge";
import StatTile from "@/components/ui/StatTile";

export interface StatsRowProps {
  overdueCards: number;
  quizzesToTake: number;
  progressPercent: number | null;
  progressCourseTitle: string | null;
  backlogWarning: boolean;
}

export default function StatsRow({
  overdueCards,
  quizzesToTake,
  progressPercent,
  progressCourseTitle,
  backlogWarning,
}: StatsRowProps) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <StatTile
        value={overdueCards}
        label={overdueCards === 1 ? "card due" : "cards due"}
        href="/review"
        hint={backlogWarning ? <Badge tone="warning">Backlog building up</Badge> : undefined}
      />
      <StatTile
        value={quizzesToTake}
        label={quizzesToTake === 1 ? "quiz to take" : "quizzes to take"}
        href="#quizzes"
      />
      <StatTile
        value={progressPercent != null ? `${progressPercent}%` : "—"}
        label={progressCourseTitle ? `through ${progressCourseTitle}` : "no course in progress"}
      />
    </div>
  );
}
