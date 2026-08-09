import { describe, expect, it } from "vitest";

import {
  loadingPracticeSectionState,
  practiceSectionStateFromAssessment,
  practiceSectionStateFromLoadError,
} from "@/components/chapter/practiceAssessmentState";
import type {
  ApiErrorDetail,
  PracticeAssessmentOut,
  PracticeQuestionOut,
} from "@/lib/api/client";

const extractionDetail: ApiErrorDetail = {
  code: "invalid_model_output",
  failure_category: "llm_response_invalid",
  message: "The model returned invalid JSON.",
  remediation: "Retry extraction after checking the model.",
};

function makeQuestion(overrides: Partial<PracticeQuestionOut> = {}): PracticeQuestionOut {
  return {
    id: "question-1",
    problem_number: "1",
    source_ref: "p. 12",
    concept: { id: "concept-1", label: "Newton's second law", slug: "newtons-second-law" },
    stem_md: "What is the net force?",
    choices: ["4 N", "6 N", "8 N"],
    answered: null,
    ...overrides,
  };
}

function makeAssessment(
  overrides: Partial<PracticeAssessmentOut & { error_detail: ApiErrorDetail | null }> = {},
): PracticeAssessmentOut & { error_detail?: ApiErrorDetail | null } {
  return {
    section_id: "section-1",
    status: "ready",
    questions: [makeQuestion()],
    job_id: null,
    message: null,
    run_id: "run-1",
    error_detail: null,
    ...overrides,
  };
}

describe("practice assessment state contract", () => {
  it("creates a loading state with no retry target", () => {
    expect(loadingPracticeSectionState("section-1")).toEqual({
      kind: "loading",
      sectionId: "section-1",
      questionCount: 0,
      message: null,
      errorDetail: null,
      retryKind: null,
    });
  });

  it("reports generating assessments without error detail or retry target", () => {
    expect(
      practiceSectionStateFromAssessment(
        "section-1",
        makeAssessment({
          status: "generating",
          questions: [],
          message: "Preparing question extraction.",
        }),
      ),
    ).toEqual({
      kind: "generating",
      sectionId: "section-1",
      questionCount: 0,
      message: "Preparing question extraction.",
      errorDetail: null,
      retryKind: null,
    });
  });

  it("reports ready assessments with the ready question count", () => {
    expect(
      practiceSectionStateFromAssessment(
        "section-1",
        makeAssessment({ questions: [makeQuestion(), makeQuestion({ id: "question-2" })] }),
      ),
    ).toEqual({
      kind: "ready",
      sectionId: "section-1",
      questionCount: 2,
      message: null,
      errorDetail: null,
      retryKind: null,
    });
  });

  it("reports failed extraction assessments as restartable with learner-safe detail", () => {
    expect(
      practiceSectionStateFromAssessment(
        "section-1",
        makeAssessment({
          status: "failed",
          questions: [],
          message: "Extraction failed.",
          error_detail: extractionDetail,
        }),
      ),
    ).toEqual({
      kind: "failed",
      sectionId: "section-1",
      questionCount: 0,
      message: "Extraction failed.",
      errorDetail: extractionDetail,
      retryKind: "restart",
    });
  });

  it("reports load failures as reloadable failures", () => {
    expect(
      practiceSectionStateFromLoadError("section-1", {
        message: "Could not load practice questions.",
        detail: extractionDetail,
      }),
    ).toEqual({
      kind: "failed",
      sectionId: "section-1",
      questionCount: 0,
      message: "Could not load practice questions.",
      errorDetail: extractionDetail,
      retryKind: "reload",
    });
  });
});
