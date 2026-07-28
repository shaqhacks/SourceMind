"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import ErrorBanner from "@/components/ErrorBanner";
import Markdown from "@/components/Markdown";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import ProgressBar from "@/components/ui/ProgressBar";
import StatTile from "@/components/ui/StatTile";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  getTest,
  retakeTest,
  submitTest,
  type SubmitTestOut,
  type TestAttemptOut,
} from "@/lib/api/client";
import { useKeyboardShortcuts, type ShortcutMap } from "@/lib/hooks/useKeyboardShortcuts";
import { useRouteFocus } from "@/lib/hooks/useRouteFocus";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

export interface TestAttemptClientProps {
  courseId: string;
  attemptId: string;
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

/** "Chapter 1 test · Jul 21" — the deck only carries a chapter label, not an
 * attempt ordinal, so the date (not "attempt N") disambiguates this attempt
 * from others on the same deck without a second network round trip. */
function headerLabel(attempt: TestAttemptOut): string {
  const chapter = attempt.chapter_label ?? "Test";
  const date = new Date(attempt.created_at).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
  return `${chapter} test · ${date}`;
}

/**
 * Quiz-taking + review, in one component: before submit, TestQuestionOut
 * never carries correct_index/explanation (the API redacts them), so
 * there is nothing here to accidentally leak into the DOM pre-submit —
 * the "review" section below only renders once `result` (the submit
 * response, which does carry them) is set.
 */
export default function TestAttemptClient({ courseId, attemptId }: TestAttemptClientProps) {
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [answers, setAnswers] = useState<(number | null)[]>([]);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [unanswered, setUnanswered] = useState(false);
  const [result, setResult] = useState<SubmitTestOut | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [retaking, setRetaking] = useState(false);
  const [retakeError, setRetakeError] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useRouteFocus(headingRef);

  const handleRetake = useCallback(async () => {
    if (state.kind !== "loaded") return;
    setRetaking(true);
    setRetakeError(null);
    const { data, status } = await retakeTest(state.attempt.test_id);
    setRetaking(false);
    if (data) {
      router.push(`/course/${courseId}/test/${data.attempt_id}`);
      return;
    }
    setRetakeError(describeError(status, "Starting a retake").message);
  }, [state, courseId, router]);

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

  const goPrev = useCallback(() => {
    setQuestionIndex((index) => Math.max(0, index - 1));
    setUnanswered(false);
  }, []);

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
    const correctCount = result.results.filter((questionResult) => questionResult.correct).length;
    const totalCount = result.results.length;
    mainContent = (
      <div className="mx-auto flex w-full max-w-[760px] flex-col gap-6 p-9">
        <StatTile
          value={`${Math.round(result.score * 100)}%`}
          label={`${correctCount} of ${totalCount} correct`}
        />
        {result.added_card_ids.length > 0 && (
          <div
            role="status"
            className="flex items-center justify-between gap-3 rounded-md border border-accent/30 bg-accent-soft px-4 py-3 text-sm"
          >
            <span>
              {result.added_card_ids.length} missed concept
              {result.added_card_ids.length === 1 ? "" : "s"} added to your reviews.
            </span>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3">
          {result.due_now_count > 0 && (
            <Link
              href={`/review?course=${courseId}&start=due`}
              className="rounded-md bg-accent-700 px-4 py-2 text-sm font-medium text-background transition-colors hover:bg-accent-800"
            >
              Start review — {result.due_now_count} card{result.due_now_count === 1 ? "" : "s"} due
              now
            </Link>
          )}
          <Button
            variant="primary"
            onClick={() => void handleRetake()}
            disabled={retaking}
            title="Same questions, no generation cost"
          >
            Retake test
          </Button>
        </div>
        {retakeError && <ErrorBanner message={retakeError} onRetry={() => void handleRetake()} />}
        <ul className="flex flex-col gap-6">
          {result.results.map((questionResult, index) => {
            const question = attempt.questions[index];
            return (
              <li key={index}>
                <Card className="flex flex-col gap-2 p-6">
                  <p className="text-sm font-medium">{question.question}</p>
                  {questionResult.correct ? (
                    <Badge tone="good">Correct</Badge>
                  ) : (
                    <Badge tone="accent">Incorrect</Badge>
                  )}
                  <p className="text-sm text-muted-foreground">
                    Your answer:{" "}
                    {questionResult.your_answer !== null
                      ? question.choices[questionResult.your_answer]
                      : "(none)"}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    Correct answer: {question.choices[questionResult.correct_index]}
                  </p>
                  <div className="text-sm">
                    <Markdown>{questionResult.explanation}</Markdown>
                  </div>
                </Card>
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
      <div className="mx-auto flex w-full max-w-[760px] flex-col gap-6 p-9">
        <div className="flex items-center gap-3.5">
          <div className="flex-1">
            <ProgressBar
              percent={((questionIndex + 1) / questionCount) * 100}
              label="Quiz progress"
            />
          </div>
          <p role="status" className="shrink-0 text-sm font-semibold text-muted-foreground">
            Question {questionIndex + 1} of {questionCount}
          </p>
        </div>
        <Card className="flex flex-col gap-5 p-8 shadow-md">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            {attempt.chapter_label ?? "Test"}
          </span>
          <h2 className="font-heading text-[22px] leading-snug">{question.question}</h2>
          <fieldset className="flex flex-col gap-2.5">
            <legend className="sr-only">Choices</legend>
            {question.choices.map((choice, index) => (
              <label
                key={index}
                className="flex items-start gap-3 rounded-md border border-divider bg-background px-4 py-3.5 text-[15px] leading-snug transition-colors hover:border-muted-foreground has-checked:border-[1.5px] has-checked:border-accent has-checked:bg-accent-soft"
              >
                <input
                  type="radio"
                  name={`question-${questionIndex}`}
                  checked={answers[questionIndex] === index}
                  onChange={() => selectAnswer(index)}
                  style={{ accentColor: "var(--accent)" }}
                  className="mt-0.5"
                />
                <span aria-hidden="true" className="font-semibold text-muted-foreground">
                  {index + 1}
                </span>
                <span>{choice}</span>
              </label>
            ))}
          </fieldset>
          {unanswered && (
            <p role="alert" className="text-sm text-red-600 dark:text-red-400">
              Select an answer before continuing.
            </p>
          )}
          {submitError && <ErrorBanner message={submitError} onRetry={handleSubmit} />}
          <div className="flex items-center justify-between">
            <Button
              variant="ghost"
              onClick={goPrev}
              disabled={questionIndex === 0}
              className="text-sm"
            >
              ← Previous
            </Button>
            <Button variant="primary" onClick={goNext} disabled={submitting}>
              {questionIndex + 1 < questionCount ? "Next question" : "Submit quiz"}
            </Button>
          </div>
        </Card>
        <p className="text-center text-[13px] text-muted-foreground">
          <kbd className="rounded-md border border-divider px-1.5 py-0.5 font-sans">1–4</kbd> pick an
          answer ·{" "}
          <kbd className="rounded-md border border-divider px-1.5 py-0.5 font-sans">Enter</kbd> next
          / submit
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="flex items-center gap-3 border-b border-border px-6 py-3">
        <Link
          href="/tests"
          aria-label="Back to tests"
          className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-surface-raised transition-colors hover:bg-foreground/[0.07]"
        >
          <ArrowLeft aria-hidden="true" className="h-4 w-4" strokeWidth={2.75} />
        </Link>
        <h1
          ref={headingRef}
          tabIndex={-1}
          className="truncate text-sm font-medium text-muted-foreground outline-none"
        >
          {state.kind === "loaded" ? headerLabel(state.attempt) : "Quiz"}
        </h1>
        <Link
          href="/tests"
          className="ml-auto shrink-0 rounded-md border border-border bg-surface-raised px-3 py-1.5 text-sm font-medium transition-colors hover:bg-foreground/[0.07]"
        >
          Save &amp; exit
        </Link>
      </div>
      {mainContent}
    </>
  );
}
