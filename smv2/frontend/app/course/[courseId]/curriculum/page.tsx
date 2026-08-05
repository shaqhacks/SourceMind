import CurriculumReview from "@/components/curriculum/CurriculumReview";
import WorkspaceModeGate from "@/components/workspace/WorkspaceModeGate";

export default async function CurriculumReviewPage({ params }: { params: Promise<{ courseId: string }> }) {
  const { courseId } = await params;
  return (
    <WorkspaceModeGate courseId={courseId}>
      <CurriculumReview courseId={courseId} />
    </WorkspaceModeGate>
  );
}
