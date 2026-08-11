import { gradeCard, type ApiResult, type GradeCardOut } from "@/lib/api/client";
import { notifyReviewSettled } from "@/lib/review/reviewBus";
import type { ReviewGrade } from "@/lib/review/intervalPreview";

export async function gradeCardAndNotify(
  cardId: string,
  grade: ReviewGrade,
  elapsedMs: number,
): Promise<ApiResult<GradeCardOut>> {
  const result = await gradeCard(cardId, { grade, elapsed_ms: elapsedMs });
  if (result.ok) notifyReviewSettled();
  return result;
}
