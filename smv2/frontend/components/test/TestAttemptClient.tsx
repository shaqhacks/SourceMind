"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

import ErrorBanner from "@/components/ErrorBanner";
import Markdown from "@/components/Markdown";
import { getTest, submitTest, type SubmitTestOut, type TestAttemptOut } from "@/lib/api/client";
import { useKeyboardShortcuts, type ShortcutMap } from "@/lib/hooks/useKeyboardShortcuts";
import { useRouteFocus } from "@/lib/hooks/useRouteFocus";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

export interface TestAttemptClientProps {
  courseId: string;
  attemptId: string;
}

interface FetchError {
  status?: number;
  message: string;
}

function describeError(status: number | undefined, action: string): FetchError {
  if (status === undefined) {
    return { message: `${action}: could not reach the API. Is the backend running?` };
  }
  return { status, message: `${action} failed (HTTP ${status}).` };
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "loaded"; attempt: TestAttemptOut };

async function fetchAttempt(attemptId: string): Promise<LoadState> {
  const { data, status } = await getTest(attemptId);
  if (!data) return { kind: "error", error: describeError(status, "Loading quiz") };
  return { kind: "loaded", attempt: data };
}

/**
 * Quiz-taking + review, in one component: before submit, TestQuestionOut
 * never carries correct_index/explanation (the API redacts them), so
 * there is nothing here to accidentally leak into the DOM pre-submit —
 * the "review" section below only renders once `result` (the submit
 * response, which does carry them) is set.
 */
export default function TestAttemptClient({ courseId, attemptId }: TestAttemptClientProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [answers, setAnswers] = useState<(number | null)[]>([]);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [unanswered, setUnanswered] = useState(false);
  const [result, setResult] = useState<SubmitTestOut | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useRouteFocus(headingRef);

  // Retry-button callback: no unmount guard needed, only ever runs from a
  // user click on an already-mounted ErrorBanner.
  const retry = useCallback(async () => {
    setState({ kind: "loading" });
    const result = await fetchAttempt(attemptId);
    setState(result);
    if (result.kind === "loaded") setAnswers(new Array(result.attempt.questions.length).fill(null));
  }, [attemptId]);

  // Mount-only fetch: setState happens inside the .then() callback rather
  // than through `retry` directly, so an unmount during the in-flight
  // request can't set state on a gone component.
  useEffect(() => {
    let active = true;
    fetchAttempt(attemptId).then((result) => {
      if (!active) return;
      setState(result);
      if (result.kind === "loaded") {
        setAnswers(new Array(result.attempt.questions.length).fill(null));
      }
    });
    return () => {
      active = false;
    };
  }, [attemptId]);

  const selectAnswer = useCallback(
    (choiceIndex: number) => {
      setAnswers((prev) => {
        const next = [...prev];
        next[questionIndex] = choiceIndex;
        return next;
      });
      setUnanswered(false);
    },
    [questionIndex],
  );

  const handleSubmit = useCallback(async () => {
    if (answers.some((answer) => answer === null)) {
      setUnanswered(true);
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    const { data, status } = await submitTest(attemptId, answers as number[]);
    setSubmitting(false);
    if (data) {
      setResult(data);
      notifyReviewSettled();
    } else {
      setSubmitError(describeError(status, "Submitting quiz").message);
    }
  }, [attemptId, answers]);

  const goNext = useCallback(() => {
    if (state.kind !== "loaded") return;
    if (answers[questionIndex] === null) {
      setUnanswered(true);
      return;
    }
    if (questionIndex + 1 < state.attempt.questions.length) {
      setQuestionIndex((index) => index + 1);
      setUnanswered(false);
    } else {
      void handleSubmit();
    }
  }, [state, answers, questionIndex, handleSubmit]);

  const questionCount = state.kind === "loaded" ? state.attempt.questions.length : 0;
  const choiceCount =
    state.kind === "loaded" ? state.attempt.questions[questionIndex]?.choices.length ?? 0 : 0;

  const shortcutMap: ShortcutMap = result
    ? {}
    : {
        "1": () => choiceCount > 0 && selectAnswer(0),
        "2": () => choiceCount > 1 && selectAnswer(1),
        "3": () => choiceCount > 2 && selectAnswer(2),
        "4": () => choiceCount > 3 && selectAnswer(3),
        enter: goNext,
      };
  useKeyboardShortcuts(shortcutMap);

  let mainContent: React.ReactNode;

  if (state.kind === "loading") {
    mainContent = (
      <p role="status" className="p-8 text-sm text-muted-foreground">
        Loading quiz…
      </p>
    );
  } else if (state.kind === "error") {
    mainContent = (
      <div className="p-8">
        <ErrorBanner
          status={state.error.status}
          message={state.error.message}
          onRetry={() => void retry()}
        />
      </div>
    );
  } else if (result) {
    const { attempt } = state;
    mainContent = (
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 p-8">
        <h2 className="text-lg font-semibold">Score: {Math.round(result.score * 100)}%</h2>
        <ul className="flex flex-col gap-6">
          {result.results.map((questionResult, index) => {
            const question = attempt.questions[index];
            return (
              <li key={index} className="rounded-lg border border-border p-4">
                <p className="mb-2 text-sm font-medium">{question.question}</p>
                <p
                  className={`mb-2 text-sm font-medium ${
                    questionResult.correct
                      ? "text-green-700 dark:text-green-400"
                      : "text-red-700 dark:text-red-400"
                  }`}
                >
                  {questionResult.correct ? "✓ Correct" : "✗ Incorrect"}
                </p>
                <p className="text-sm text-muted-foreground">
                  Your answer:{" "}
                  {questionResult.your_answer !== null
                    ? question.choices[questionResult.your_answer]
                    : "(none)"}
                </p>
                <p className="text-sm text-muted-foreground">
                  Correct answer: {question.choices[questionResult.correct_index]}
                </p>
                <div className="mt-2 text-sm">
                  <Markdown>{questionResult.explanation}</Markdown>
                </div>
              </li>
            );
          })}
        </ul>
        <Link href={`/course/${courseId}`} className="text-sm font-medium text-accent underline">
          Back to course
        </Link>
      </div>
    );
  } else {
    const { attempt } = state;
    const question = attempt.questions[questionIndex];
    mainContent = (
      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 p-8">
        <p role="status" className="text-sm text-muted-foreground">
          {questionIndex + 1} of {questionCount}
        </p>
        <h2 className="text-base font-semibold">{question.question}</h2>
        <fieldset className="flex flex-col gap-2">
          <legend className="sr-only">Choices</legend>
          {question.choices.map((choice, index) => (
            <label
              key={index}
              className="flex items-center gap-2 rounded-md border border-border px-3 py-2 text-sm"
            >
              <input
                type="radio"
                name={`question-${questionIndex}`}
                checked={answers[questionIndex] === index}
                onChange={() => selectAnswer(index)}
              />
              {choice}
            </label>
          ))}
        </fieldset>
        {unanswered && (
          <p role="alert" className="text-sm text-red-600 dark:text-red-400">
            Select an answer before continuing.
          </p>
        )}
        {submitError && <ErrorBanner message={submitError} onRetry={handleSubmit} />}
        <button
          type="button"
          onClick={goNext}
          disabled={submitting}
          className="self-start rounded-md bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-black"
        >
          {questionIndex + 1 < questionCount ? "Next (Enter)" : "Submit (Enter)"}
        </button>
      </div>
    );
  }

  return (
    <>
      <div className="border-b border-border px-8 py-4">
        <h1 ref={headingRef} tabIndex={-1} className="text-lg font-semibold outline-none">
          Quiz
        </h1>
      </div>
      {mainContent}
    </>
  );
}
