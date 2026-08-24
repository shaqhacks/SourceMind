import SkillMapEditor from "@/components/skills/SkillMapEditor";

interface SkillMapEditPageProps {
  params: Promise<{ courseId: string }>;
}

export default async function SkillMapEditPage({ params }: SkillMapEditPageProps) {
  const { courseId } = await params;

  return <SkillMapEditor courseId={courseId} />;
}
