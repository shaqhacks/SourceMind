"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import Markdown from "@/components/Markdown";
import RecoveryBanner from "@/components/RecoveryBanner";
import Button from "@/components/ui/Button";
import {
  loadingPracticeSectionState,
  practiceSectionStateFromAssessment,
  practiceSectionStateFromLoadError,
  practiceSectionStateSignature,
  type PracticeSectionState,
} from "@/components/chapter/practiceAssessmentState";
import {
  getPracticeAssessment,
  startPracticeAssessment,
  submitPracticeAnswer,
  type PracticeAnsweredOut,
  type PracticeAssessmentOut,
  type PracticeQuestionOut,
  type SubmitPracticeAnswerOut,
} from "@/lib/api/client";
import { apiErrorDetail, describeError, type FetchError } from "@/lib/api/errors";

interface InlinePracticeAssessmentProps {
  courseId: string;
  sectionId: string;
  retryVersion?: number;
  onStateChange?: (state: PracticeSectionState) => void;
}

type AnswerState = Pick<
  PracticeAnsweredOut | SubmitPracticeAnswerOut,
  | "correct"
  | "correct_index"
  | "evidence_count"
  | "evidence_state"
  | "explanation_md"
  | "readiness_estimate"
  | "selected_index"
>;
type AnswerMap = Record<string, AnswerState>;
type SubmitErrorMap = Record<string, string | undefined>;

const POLL_MS = 1500;

const choiceSchema = {
  ...defaultSchema,
  attributes: {
    ...defaultSchema.attributes,
    code: [["className", /^language-./, "math-inline", "math-display"]],
  },
};

function Inline({ children }: { children?: ReactNode }) {
  return <span>{children}</span>;
}

const choiceMarkdownComponents: Components = {
  p: Inline,
  a: Inline,
  h1: Inline,
  h2: Inline,
  h3: Inline,
  h4: Inline,
  h5: Inline,
  h6: Inline,
  ul: Inline,
  ol: Inline,
  li: Inline,
  table: Inline,
  thead: Inline,
  tbody: Inline,
  tr: Inline,
  th: Inline,
  td: Inline,
  pre: Inline,
  blockquote: Inline,
  img: () => null,
};

function ChoiceMarkdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[
        [rehypeSanitize, choiceSchema],
        [rehypeKatex, { trust: false, strict: "warn" }],
      ]}
      components={choiceMarkdownComponents}
    >
      {children}
    </ReactMarkdown>
  );
}

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
  retryVersion = 0,
  onStateChange,
}: InlinePracticeAssessmentProps) {
  const [assessment, setAssessment] = useState<PracticeAssessmentOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [loadError, setLoadError] = useState<FetchError | null>(null);
  const [retryError, setRetryError] = useState<FetchError | null>(null);
  const [answers, setAnswers] = useState<AnswerMap>({});
  const [submitting, setSubmitting] = useState<Record<string, boolean>>({});
  const [submitErrors, setSubmitErrors] = useState<SubmitErrorMap>({});
  const startedForRef = useRef<string | null>(null);
  const loadSeqRef = useRef(0);
  const mountedRef = useRef(false);
  const onStateChangeRef = useRef(onStateChange);
  const lastEmittedStateRef = useRef<string | null>(null);
  const currentSectionStateRef = useRef<PracticeSectionState | null>(null);
  const consumedRetryVersionRef = useRef(retryVersion);
  const retryingFailedAssessmentRef = useRef(false);

  useEffect(() => {
    onStateChangeRef.current = onStateChange;
  }, [onStateChange]);

  const emitSectionState = useCallback((nextState: PracticeSectionState) => {
    if (!mountedRef.current) {
      return;
    }
    currentSectionStateRef.current = nextState;
    const signature = practiceSectionStateSignature(nextState);
    if (lastEmittedStateRef.current === signature) {
      return;
    }
    lastEmittedStateRef.current = signature;
    onStateChangeRef.current?.(nextState);
  }, []);

  const applyAssessment = useCallback((next: PracticeAssessmentOut) => {
    if (!mountedRef.current) {
      return;
    }
    setAssessment(next);
    setLoadError(null);
    setRetryError(null);
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
    emitSectionState(practiceSectionStateFromAssessment(sectionId, next));
  }, [emitSectionState, sectionId]);

  const isCurrentLoad = useCallback((loadSeq: number) => {
    return mountedRef.current && loadSeqRef.current === loadSeq;
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
        setStarting(false);
      }
      if (showLoading) {
        setLoading(true);
        emitSectionState(loadingPracticeSectionState(sectionId));
      }
      setLoadError(null);

      const result = await getPracticeAssessment(courseId, sectionId);
      if (!isCurrentLoad(loadSeq)) {
        return;
      }
      setLoading(false);

      if (!result.ok || !result.data) {
        const nextError = {
          message: "Could not load practice questions.",
          status: result.status,
        };
        setLoadError(nextError);
        emitSectionState(practiceSectionStateFromLoadError(sectionId, nextError));
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
      if (!isCurrentLoad(loadSeq)) {
        return;
      }
      setStarting(false);

      if (!startResult.ok || !startResult.data) {
        const nextError = describeError(
          startResult.status,
          "Starting practice questions",
          startResult.error,
        );
        setLoadError(nextError);
        emitSectionState(practiceSectionStateFromLoadError(sectionId, nextError));
        return;
      }

      applyAssessment(startResult.data);
    },
    [applyAssessment, courseId, emitSectionState, isCurrentLoad, sectionId],
  );

  const retryFailedAssessment = useCallback(async () => {
    if (retryingFailedAssessmentRef.current) {
      return;
    }
    retryingFailedAssessmentRef.current = true;
    const loadSeq = loadSeqRef.current + 1;
    loadSeqRef.current = loadSeq;
    startedForRef.current = `${courseId}:${sectionId}`;
    setRetryError(null);
    emitSectionState({
      kind: "generating",
      sectionId,
      questionCount: 0,
      message: "Preparing questions.",
      errorDetail: null,
      retryKind: null,
    });

    const startResult = await startPracticeAssessment(courseId, sectionId);
    if (!isCurrentLoad(loadSeq)) {
      retryingFailedAssessmentRef.current = false;
      return;
    }

    if (!startResult.ok || !startResult.data) {
      retryingFailedAssessmentRef.current = false;
      const nextError = describeError(
        startResult.status,
        "Restarting practice questions",
        startResult.error,
      );
      setRetryError(nextError);
      emitSectionState({
        kind: "failed",
        sectionId,
        questionCount: 0,
        message: nextError.message,
        errorDetail: nextError.detail ?? null,
        retryKind: "restart",
      });
      return;
    }

    retryingFailedAssessmentRef.current = false;
    applyAssessment(startResult.data);
  }, [applyAssessment, courseId, emitSectionState, isCurrentLoad, sectionId]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      loadSeqRef.current += 1;
      retryingFailedAssessmentRef.current = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (active) {
        void loadAssessment({ resetStart: true, resetState: true, showLoading: true });
      }
    });
    return () => {
      active = false;
      loadSeqRef.current += 1;
    };
  }, [loadAssessment]);

  useEffect(() => {
    if (retryVersion <= consumedRetryVersionRef.current) {
      return;
    }

    const currentState = currentSectionStateRef.current;
    if (currentState?.kind !== "failed") {
      return;
    }

    consumedRetryVersionRef.current = retryVersion;
    if (currentState.retryKind === "reload") {
      void loadAssessment({ resetStart: true, showLoading: true });
      return;
    }
    void retryFailedAssessment();
  }, [loadAssessment, retryFailedAssessment, retryVersion]);

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
          const nextError = {
            message: "Could not refresh practice questions.",
            status: result.status,
          };
          setLoadError(nextError);
          emitSectionState(practiceSectionStateFromLoadError(sectionId, nextError));
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
  }, [applyAssessment, assessment?.status, courseId, emitSectionState, sectionId]);

  async function handleSubmit(question: PracticeQuestionOut, selectedIndex: number) {
    if (answers[question.id] || submitting[question.id]) {
      return;
    }

    const submitSeq = loadSeqRef.current;
    setSubmitting((current) => ({ ...current, [question.id]: true }));
    setSubmitErrors((current) => ({ ...current, [question.id]: undefined }));

    const result = await submitPracticeAnswer(courseId, question.id, selectedIndex);
    if (!isCurrentLoad(submitSeq)) {
      return;
    }
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
      <section
        aria-live="polite"
        className="rounded-md border border-border px-4 py-3 text-sm text-muted-foreground"
        role="status"
      >
        Preparing practice questions...
      </section>
    );
  }

  if (loadError) {
    return (
        <RecoveryBanner
          message={loadError.message}
          errorDetail={loadError.detail}
          onRetry={() => void loadAssessment({ resetStart: true, showLoading: true })}
        />
    );
  }

  if (!assessment) {
    return null;
  }

  if (assessment.status === "generating") {
    return (
      <section
        aria-live="polite"
        className="rounded-md border border-border px-4 py-3 text-sm text-muted-foreground"
        role="status"
      >
        Preparing practice questions...
      </section>
    );
  }

  if (assessment.status === "failed") {
    const errorDetail = apiErrorDetail({ detail: assessment.error_detail });
    return (
      <div className="flex flex-col gap-2">
        <RecoveryBanner
          message={
            errorDetail?.message ?? assessment.message ?? "Practice question extraction failed."
          }
          errorDetail={errorDetail}
          onRetry={() => void retryFailedAssessment()}
        />
        {retryError ? (
          <RecoveryBanner
            message={retryError.message}
            errorDetail={retryError.detail}
            onRetry={() => void retryFailedAssessment()}
          />
        ) : null}
      </div>
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
                    <ChoiceMarkdown>{choice}</ChoiceMarkdown>
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
                  <span>
                    {answer.readiness_estimate == null
                      ? "Readiness needs more evidence"
                      : `${Math.round(answer.readiness_estimate * 100)}% readiness`}
                  </span>
                  <span>
                    {answer.evidence_count} evidence item{answer.evidence_count === 1 ? "" : "s"}
                  </span>
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
