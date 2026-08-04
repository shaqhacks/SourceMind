import CurriculumReview from "@/components/curriculum/CurriculumReview";

export default async function CurriculumReviewPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await params;
  return <CurriculumReview courseId={courseId} />;
}
