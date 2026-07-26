import CompetencyDetailView from "@/components/skills/CompetencyDetailView";

interface CompetencyDetailPageProps {
  params: Promise<{ courseId: string; skillId: string }>;
}

export default async function CompetencyDetailPage({ params }: CompetencyDetailPageProps) {
  const { courseId, skillId } = await params;

  return <CompetencyDetailView courseId={courseId} skillId={skillId} />;
}
