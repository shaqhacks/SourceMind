import SkillMapView from "@/components/skills/SkillMapView";

interface SkillMapPageProps {
  params: Promise<{ courseId: string }>;
}

/**
 * SkillMapView is a client component that does its own data fetching (see
 * CoursePage's comment for the same pattern) — this page's only job is
 * unwrapping the (Promise-typed) route param.
 */
export default async function SkillMapPage({ params }: SkillMapPageProps) {
  const { courseId } = await params;

  return <SkillMapView courseId={courseId} />;
}
