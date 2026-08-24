import CourseHomeClient from "@/components/course/CourseHomeClient";

interface CoursePageProps {
  params: Promise<{ courseId: string }>;
}

/**
 * Course landing page: the first page a course opens onto, with entries to
 * Lessons, Flashcards, the Skill map, and Tests. The reader itself lives at
 * /course/[courseId]/read.
 */
export default async function CoursePage({ params }: CoursePageProps) {
  const { courseId } = await params;

  return <CourseHomeClient courseId={courseId} />;
}
