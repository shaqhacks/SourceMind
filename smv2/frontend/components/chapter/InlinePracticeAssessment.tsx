"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Markdown from "@/components/Markdown";
import Button from "@/components/ui/Button";
import {
  getPracticeAssessment,
  startPracticeAssessment,
  submitPracticeAnswer,
  type PracticeAnsweredOut,
  type PracticeAssessmentOut,
  type PracticeQuestionOut,
  type SubmitPracticeAnswerOut,
} from "@/lib/api/client";

interface InlinePracticeAssessmentProps {
  courseId: string;
  sectionId: string;
}

type AnswerState = Pick<
  PracticeAnsweredOut | SubmitPracticeAnswerOut,
  | "correct"
  | "correct_index"
  | "explanation_md"
  | "mastery_points"
  | "points_delta"
  | "selected_index"
>;
type AnswerMap = Record<string, AnswerState>;
type SubmitErrorMap = Record<string, string | undefined>;

const POLL_MS = 1500;

function answerSummary(answer: AnswerState) {
  return answer.correct ? "Correct" : "Incorrect";
}

function choiceClassName(
  question: PracticeQuestionOut,
  choiceIndex: number,
  answer?: AnswerState,
) {
  if (!answer) {
    return "w-full text-left";
  }
  if (choiceIndex === answer.correct_index) {
    return "w-full border-status-good/60 bg-status-good-soft text-left";
  }
  if (choiceIndex === answer.selected_index && !answer.correct) {
    return "w-full border-status-serious/60 bg-status-serious-soft text-left";
  }
  return question.choices.length > 2
    ? "w-full text-left opacity-70"
    : "w-full text-left";
}

export default function InlinePracticeAssessment({
  courseId,
  sectionId,
}: InlinePracticeAssessmentProps) {
  const [assessment, setAssessment] = useState<PracticeAssessmentOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [loadError, setLoadError] = useState<{ message: string; status?: number } | null>(null);
  const [answers, setAnswers] = useState<AnswerMap>({});
  const [submitting, setSubmitting] = useState<Record<string, boolean>>({});
  const [submitErrors, setSubmitErrors] = useState<SubmitErrorMap>({});
  const startedForRef = useRef<string | null>(null);
  const loadSeqRef = useRef(0);

  const applyAssessment = useCallback((next: PracticeAssessmentOut) => {
    setAssessment(next);
    setLoadError(null);
    if (next.status === "ready") {
      setAnswers((current) => {
        const merged = { ...current };
        for (const question of next.questions ?? []) {
          if (question.answered) {
            merged[question.id] = question.answered;
          }
        }
        return merged;
      });
    }
  }, []);

  const loadAssessment = useCallback(
    async ({
      resetStart = false,
      resetState = false,
      showLoading = false,
    }: { resetStart?: boolean; resetState?: boolean; showLoading?: boolean } = {}) => {
      const loadSeq = loadSeqRef.current + 1;
      loadSeqRef.current = loadSeq;
      if (resetStart) {
        startedForRef.current = null;
      }
      if (resetState) {
        setAssessment(null);
        setAnswers({});
        setSubmitting({});
        setSubmitErrors({});
      }
      if (showLoading) {
        setLoading(true);
      }
      setLoadError(null);

      const result = await getPracticeAssessment(courseId, sectionId);
      if (loadSeqRef.current !== loadSeq) {
        return;
      }
      setLoading(false);

      if (!result.ok || !result.data) {
        setLoadError({
          message: "Could not load practice questions.",
          status: result.status,
        });
        return;
      }

      if (result.data.status !== "not_started") {
        applyAssessment(result.data);
        return;
      }

      const startKey = `${courseId}:${sectionId}`;
      if (startedForRef.current === startKey) {
        applyAssessment(result.data);
        return;
      }

      startedForRef.current = startKey;
      setStarting(true);
      const startResult = await startPracticeAssessment(courseId, sectionId);
      if (loadSeqRef.current !== loadSeq) {
        return;
      }
      setStarting(false);

      if (!startResult.ok || !startResult.data) {
        setLoadError({
          message: "Could not start practice questions.",
          status: startResult.status,
        });
        return;
      }

      applyAssessment(startResult.data);
    },
    [applyAssessment, courseId, sectionId],
  );

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) {
        void loadAssessment({ resetStart: true, resetState: true, showLoading: true });
      }
    });
    return () => {
      active = false;
    };
  }, [loadAssessment]);

  useEffect(() => {
    if (assessment?.status !== "generating") {
      return;
    }

    let active = true;
    let timeout: number | null = null;

    const schedulePoll = () => {
      timeout = window.setTimeout(async () => {
        const result = await getPracticeAssessment(courseId, sectionId);
        if (!active) {
          return;
        }
        if (!result.ok || !result.data) {
          setLoadError({
            message: "Could not refresh practice questions.",
            status: result.status,
          });
          return;
        }
        applyAssessment(result.data);
        if (result.data.status === "generating") {
          schedulePoll();
        }
      }, POLL_MS);
    };

    schedulePoll();

    return () => {
      active = false;
      if (timeout !== null) {
        window.clearTimeout(timeout);
      }
    };
  }, [applyAssessment, assessment?.status, courseId, sectionId]);

  async function handleSubmit(question: PracticeQuestionOut, selectedIndex: number) {
    if (answers[question.id] || submitting[question.id]) {
      return;
    }

    setSubmitting((current) => ({ ...current, [question.id]: true }));
    setSubmitErrors((current) => ({ ...current, [question.id]: undefined }));

    const result = await submitPracticeAnswer(courseId, question.id, selectedIndex);
    setSubmitting((current) => ({ ...current, [question.id]: false }));

    if (!result.ok || !result.data) {
      setSubmitErrors((current) => ({
        ...current,
        [question.id]: "Could not submit answer. Try again.",
      }));
      return;
    }

    const submittedAnswer = result.data;
    setAnswers((current) => ({ ...current, [question.id]: submittedAnswer }));
  }

  if (loading || starting) {
    return (
      <section className="rounded-md border border-border px-4 py-3 text-sm text-muted-foreground">
        Preparing practice questions...
      </section>
    );
  }

  if (loadError) {
    return (
      <ErrorBanner
        message={loadError.message}
        status={loadError.status}
        onRetry={() => void loadAssessment({ resetStart: true, showLoading: true })}
      />
    );
  }

  if (!assessment) {
    return null;
  }

  if (assessment.status === "generating") {
    return (
      <section className="rounded-md border border-border px-4 py-3 text-sm text-muted-foreground">
        Preparing practice questions...
      </section>
    );
  }

  if (assessment.status === "failed") {
    return (
      <ErrorBanner
        message={assessment.message ?? "Practice question extraction failed."}
        onRetry={() => void loadAssessment({ resetStart: true, showLoading: true })}
      />
    );
  }

  const questions = assessment.questions ?? [];

  return (
    <section className="space-y-3">
      {questions.map((question, index) => {
        const answer = answers[question.id];
        const isSubmitting = Boolean(submitting[question.id]);
        return (
          <article key={question.id} className="rounded-md border border-border p-4">
            <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>Question {question.problem_number || index + 1}</span>
              <span>{question.source_ref}</span>
              <span>{question.concept.label}</span>
            </div>

            <div className="prose prose-sm max-w-none dark:prose-invert">
              <Markdown>{question.stem_md}</Markdown>
            </div>

            <div className="mt-4 grid gap-2">
              {question.choices.map((choice, choiceIndex) => (
                <Button
                  key={`${question.id}-${choiceIndex}`}
                  aria-pressed={answer?.selected_index === choiceIndex}
                  className={choiceClassName(question, choiceIndex, answer)}
                  disabled={Boolean(answer) || isSubmitting}
                  onClick={() => void handleSubmit(question, choiceIndex)}
                  variant="secondary"
                >
                  <span className="prose prose-sm block max-w-none text-inherit dark:prose-invert [&_*]:text-inherit [&>p]:m-0">
                    <Markdown>{choice}</Markdown>
                  </span>
                </Button>
              ))}
            </div>

            {submitErrors[question.id] && !answer ? (
              <p className="mt-3 text-sm text-status-serious">{submitErrors[question.id]}</p>
            ) : null}

            {answer ? (
              <div className="mt-4 rounded-md border border-border bg-muted-foreground/5 p-3">
                <div className="mb-2 flex flex-wrap items-center gap-3 text-sm font-medium">
                  <span>{answerSummary(answer)}</span>
                  <span>Concept points {answer.mastery_points}</span>
                </div>
                <div className="prose prose-sm max-w-none dark:prose-invert">
                  <Markdown>{answer.explanation_md}</Markdown>
                </div>
              </div>
            ) : null}
          </article>
        );
      })}
    </section>
  );
}
