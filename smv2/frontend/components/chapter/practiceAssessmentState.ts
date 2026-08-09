import type { ApiErrorDetail, PracticeAssessmentOut } from "@/lib/api/client";
import type { FetchError } from "@/lib/api/errors";

export type PracticeSectionState =
  | {
      kind: "loading";
      sectionId: string;
      questionCount: 0;
      message: null;
      errorDetail: null;
      retryKind: null;
    }
  | {
      kind: "generating";
      sectionId: string;
      questionCount: 0;
      message: string | null;
      errorDetail: null;
      retryKind: null;
    }
  | {
      kind: "ready";
      sectionId: string;
      questionCount: number;
      message: null;
      errorDetail: null;
      retryKind: null;
    }
  | {
      kind: "failed";
      sectionId: string;
      questionCount: 0;
      message: string;
      errorDetail: ApiErrorDetail | null;
      retryKind: "reload" | "restart";
    };

type PracticeAssessmentWithErrorDetail = PracticeAssessmentOut & {
  error_detail?: ApiErrorDetail | null;
};

export function loadingPracticeSectionState(sectionId: string): PracticeSectionState {
  return {
    kind: "loading",
    sectionId,
    questionCount: 0,
    message: null,
    errorDetail: null,
    retryKind: null,
  };
}

export function practiceSectionStateFromLoadError(
  sectionId: string,
  error: Pick<FetchError, "message" | "detail">,
): PracticeSectionState {
  return {
    kind: "failed",
    sectionId,
    questionCount: 0,
    message: error.message,
    errorDetail: error.detail ?? null,
    retryKind: "reload",
  };
}

export function practiceSectionStateFromAssessment(
  sectionId: string,
  assessment: PracticeAssessmentWithErrorDetail,
): PracticeSectionState {
  if (assessment.status === "ready") {
    return {
      kind: "ready",
      sectionId,
      questionCount: assessment.questions?.length ?? 0,
      message: null,
      errorDetail: null,
      retryKind: null,
    };
  }

  if (assessment.status === "failed") {
    return {
      kind: "failed",
      sectionId,
      questionCount: 0,
      message: assessment.message ?? "Practice question extraction failed.",
      errorDetail: assessment.error_detail ?? null,
      retryKind: "restart",
    };
  }

  if (assessment.status === "generating") {
    return {
      kind: "generating",
      sectionId,
      questionCount: 0,
      message: assessment.message ?? null,
      errorDetail: null,
      retryKind: null,
    };
  }

  return loadingPracticeSectionState(sectionId);
}

export function practiceSectionStateSignature(state: PracticeSectionState) {
  return JSON.stringify(state);
}
