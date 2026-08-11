import { describe, expect, it } from "vitest";

import {
  isPracticeSectionStartable,
  loadingPracticeSectionState,
  practiceSectionStateFromAssessment,
  practiceSectionStateFromLoadError,
  summarizePracticeSections,
  type PracticeSectionState,
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

function makeAssessment(overrides: Partial<PracticeAssessmentOut> = {}): PracticeAssessmentOut {
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

function readyState(sectionId: string, questionCount: number): PracticeSectionState {
  return {
    kind: "ready",
    sectionId,
    questionCount,
    message: null,
    errorDetail: null,
    retryKind: null,
  };
}

function generatingState(sectionId: string): PracticeSectionState {
  return {
    kind: "generating",
    sectionId,
    questionCount: 0,
    message: "Preparing questions.",
    errorDetail: null,
    retryKind: null,
  };
}

function failedState(sectionId: string, retryKind: "reload" | "restart"): PracticeSectionState {
  return {
    kind: "failed",
    sectionId,
    questionCount: 0,
    message: "Practice question extraction failed.",
    errorDetail: null,
    retryKind,
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

  it("reports not-started assessments as explicitly startable", () => {
    const state = practiceSectionStateFromAssessment(
      "section-1",
      makeAssessment({
        status: "not_started",
        questions: [],
        message: "Practice has not been generated yet.",
        run_id: null,
      }),
    );

    expect(state).toEqual({
      kind: "not_started",
      sectionId: "section-1",
      questionCount: 0,
      message: "Practice has not been generated yet.",
      errorDetail: null,
      retryKind: "start",
    });
    expect(isPracticeSectionStartable(state)).toBe(true);
    expect(isPracticeSectionStartable(generatingState("section-2"))).toBe(false);
    expect(isPracticeSectionStartable(readyState("section-3", 4))).toBe(false);
    expect(isPracticeSectionStartable(failedState("section-4", "restart"))).toBe(false);
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

  it("normalizes generated error detail before storing parent state", () => {
    expect(
      practiceSectionStateFromAssessment(
        "section-1",
        makeAssessment({
          status: "failed",
          questions: [],
          message: "Extraction failed.",
          error_detail: {
            code: 42,
            message: ["raw parser output"],
          },
        }),
      ),
    ).toEqual({
      kind: "failed",
      sectionId: "section-1",
      questionCount: 0,
      message: "Extraction failed.",
      errorDetail: null,
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

  it("summarizes mixed practice states without treating missing callbacks as ready", () => {
    const summary = summarizePracticeSections(
      {
        "sec-ready": readyState("sec-ready", 4),
        "sec-running": generatingState("sec-running"),
        "sec-failed": failedState("sec-failed", "restart"),
      },
      4,
    );

    expect(summary).toEqual({
      ready: 1,
      generating: 1,
      loading: 1,
      failed: 1,
      questions: 4,
      total: 4,
    });
  });

  it("summarizes zero practice sections as empty", () => {
    expect(summarizePracticeSections({}, 0)).toEqual({
      ready: 0,
      generating: 0,
      loading: 0,
      failed: 0,
      questions: 0,
      total: 0,
    });
  });

  it("summarizes all ready practice sections with the total question count", () => {
    expect(
      summarizePracticeSections(
        {
          "sec-a": readyState("sec-a", 2),
          "sec-b": readyState("sec-b", 3),
        },
        2,
      ),
    ).toEqual({
      ready: 2,
      generating: 0,
      loading: 0,
      failed: 0,
      questions: 5,
      total: 2,
    });
  });
});
