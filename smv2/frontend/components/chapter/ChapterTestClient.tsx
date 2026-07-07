"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import ChapterMasteryBar from "@/components/chapter/ChapterMasteryBar";
import ErrorBanner from "@/components/ErrorBanner";
import Markdown from "@/components/Markdown";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  generateTest,
  getJob,
  getSection,
  listChapters,
  listTests,
  retakeTest,
  type ChapterOut,
  type TestSummaryOut,
} from "@/lib/api/client";
import { useJobEvents } from "@/lib/hooks/useJobEvents";
import { useRouteFocus } from "@/lib/hooks/useRouteFocus";
import { formatJobProgress } from "@/lib/jobs/format";

export interface ChapterTestClientProps {
  courseId: string;
  chapterLabel: string;
}

interface PracticeSection {
  id: string;
  body: string;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "not-found" }
  | {
      kind: "ready";
      chapter: ChapterOut;
      practiceSections: PracticeSection[];
      answerSections: PracticeSection[];
    };

// Both practice exercises and their answer key are source text (the
// textbook's own printed material), fetched the same way — this isn't the
// same thing as an auto-generated TestAttempt's correct_index/explanation
// redaction (tests_service.get_test), which only applies to quizzes this
// app generates and grades itself.
async function loadSections(ids: string[]): Promise<PracticeSection[]> {
  const results = await Promise.all(ids.map((id) => getSection(id)));
  const sections: PracticeSection[] = [];
  results.forEach((result, index) => {
    if (result.data) sections.push({ id: ids[index], body: result.data.body_md });
  });
  return sections;
}

async function loadChapter(courseId: string, chapterLabel: string): Promise<LoadState> {
  const { data, status } = await listChapters(courseId);
  if (!data) return { kind: "error", error: describeError(status, "Loading chapter") };

  const chapter = data.find((candidate) => candidate.chapter_label === chapterLabel);
  if (!chapter) return { kind: "not-found" };

  // Per-section failure isolation: one bad get_section shouldn't block the
  // rest of the chapter's practice material from rendering, same
  // philosophy as GenerateAllLessons' per-job handling.
  const [practiceSections, answerSections] = await Promise.all([
    loadSections(chapter.practice_section_ids),
    loadSections(chapter.answers_section_ids),
  ]);

  return { kind: "ready", chapter, practiceSections, answerSections };
}

export default function ChapterTestClient({ courseId, chapterLabel }: ChapterTestClientProps) {
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [tests, setTests] = useState<TestSummaryOut[] | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  const [retakingTestId, setRetakingTestId] = useState<string | null>(null);
  const [retakeError, setRetakeError] = useState<string | null>(null);
  const [failureInfo, setFailureInfo] = useState<{ jobId: string; message: string | null } | null>(
    null,
  );
  // Attempt ids known before the current generation started, so the
  // settle handler can tell which attempt in the refetched list is the
  // new one to navigate into — generate_test's own response is just a
  // job_id, no attempt_id (same gap QuizzesPanel works around by refetching
  // the whole list rather than being told the new id directly).
  const knownAttemptIdsRef = useRef<Set<string>>(new Set());
  const headingRef = useRef<HTMLHeadingElement>(null);
  useRouteFocus(headingRef);

  const { job, done, stalled } = useJobEvents(jobId);
  const isGenerating = jobId !== null && !done;
  const jobFailed = done && job?.status === "failed";
  const failureMessage = failureInfo?.jobId === jobId ? failureInfo.message : null;

  const retryLoad = useCallback(() => {
    setState({ kind: "loading" });
    loadChapter(courseId, chapterLabel).then(setState);
  }, [courseId, chapterLabel]);

  // Mount/param-change fetch: state already starts as `{ kind: "loading" }`
  // (see useState above), so this just fetches directly rather than
  // routing through retryLoad's redundant synchronous reset — a plain
  // `retryLoad()` call here would touch state synchronously at the top of
  // an effect body, not inside the fetch's own callback.
  useEffect(() => {
    let active = true;
    loadChapter(courseId, chapterLabel).then((result) => {
      if (active) setState(result);
    });
    return () => {
      active = false;
    };
  }, [courseId, chapterLabel]);

  const loadTests = useCallback(() => {
    listTests(courseId).then(({ data }) => {
      if (data) setTests(data.filter((test) => test.chapter_label === chapterLabel));
    });
  }, [courseId, chapterLabel]);

  useEffect(() => {
    loadTests();
  }, [loadTests]);

  // Job settled successfully: refetch this chapter's tests and jump
  // straight into taking the new one via the existing TestAttemptClient
  // route — this page's own job is generation + history, not re-taking.
  useEffect(() => {
    if (!done || job?.status !== "succeeded") return;
    listTests(courseId).then(({ data }) => {
      if (!data) return;
      const forChapter = data.filter((test) => test.chapter_label === chapterLabel);
      setTests(forChapter);
      const freshAttempt = forChapter
        .flatMap((test) => test.attempts)
        .find((attempt) => !knownAttemptIdsRef.current.has(attempt.id));
      if (freshAttempt) router.push(`/course/${courseId}/test/${freshAttempt.id}`);
    });
  }, [done, job?.status, courseId, chapterLabel, router]);

  const handleRetake = useCallback(
    async (testId: string) => {
      setRetakingTestId(testId);
      setRetakeError(null);
      const { data, status } = await retakeTest(testId);
      setRetakingTestId(null);
      if (data) {
        router.push(`/course/${courseId}/test/${data.attempt_id}`);
        return;
      }
      setRetakeError(describeError(status, "Starting a retake").message);
    },
    [courseId, router],
  );

  // JobEvent (the SSE snapshot) carries no error text — only {id, status,
  // progress} — so surfacing the actual failure message needs a follow-up
  // plain REST fetch, same pattern as CardsCTA/LessonPane/QuizzesPanel.
  useEffect(() => {
    if (!jobFailed || !jobId) return;
    let active = true;
    getJob(jobId).then(({ data }) => {
      if (active) setFailureInfo({ jobId, message: data?.error ?? null });
    });
    return () => {
      active = false;
    };
  }, [jobFailed, jobId]);

  async function handleGenerate() {
    setStarting(true);
    setStartError(null);
    knownAttemptIdsRef.current = new Set(
      (tests ?? []).flatMap((test) => test.attempts.map((attempt) => attempt.id)),
    );
    const { data, status } = await generateTest(courseId, { chapterLabel });
    setStarting(false);
    if (data) {
      setJobId(data.job_id);
      return;
    }
    setStartError(describeError(status, "Starting chapter test generation").message);
  }

  if (state.kind === "loading") {
    return (
      <p role="status" className="p-8 text-sm text-muted-foreground">
        Loading chapter…
      </p>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="p-8">
        <ErrorBanner status={state.error.status} message={state.error.message} onRetry={retryLoad} />
      </div>
    );
  }

  if (state.kind === "not-found") {
    return (
      <div className="p-8">
        <ErrorBanner message={`No chapter named "${chapterLabel}" was found in this course.`} />
      </div>
    );
  }

  const { chapter, practiceSections, answerSections } = state;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-between border-b border-border px-8 py-4">
        <h1 ref={headingRef} tabIndex={-1} className="text-lg font-semibold outline-none">
          {chapterLabel} — Chapter test
        </h1>
        <Link href={`/course/${courseId}`} className="text-sm font-medium text-accent underline">
          Back to course
        </Link>
      </div>

      <div className="mx-auto flex w-full max-w-2xl flex-col gap-6 p-8">
        <ChapterMasteryBar stats={chapter.test_stats} />

        <div className="flex flex-col gap-3 rounded-lg border border-border p-4">
          <h2 className="text-base font-semibold">Practice material</h2>
          {practiceSections.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No practice sections detected in this chapter — take a test generated from its
              lessons instead.
            </p>
          ) : (
            <div className="flex flex-col gap-6">
              {practiceSections.map((section) => (
                <Markdown key={section.id}>{section.body}</Markdown>
              ))}
            </div>
          )}
        </div>

        {answerSections.length > 0 && (
          <details className="rounded-lg border border-border p-4">
            <summary className="cursor-pointer text-base font-semibold">Answer key</summary>
            <div className="mt-3 flex flex-col gap-6">
              {answerSections.map((section) => (
                <Markdown key={section.id}>{section.body}</Markdown>
              ))}
            </div>
          </details>
        )}

        <div className="flex flex-col gap-2">
          {jobFailed && (
            <ErrorBanner
              message={`Generation failed${failureMessage ? `: ${failureMessage}` : "."}`}
              onRetry={() => void handleGenerate()}
            />
          )}
          {isGenerating ? (
            <p role="status" className="text-sm text-muted-foreground">
              {formatJobProgress(job, stalled)}
            </p>
          ) : (
            !jobFailed && (
              <button
                type="button"
                onClick={() => void handleGenerate()}
                disabled={starting}
                title={
                  tests && tests.length > 0
                    ? "Generates a brand-new set of questions — costs an LLM call"
                    : undefined
                }
                className="self-start rounded-md bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-black"
              >
                {tests && tests.length > 0 ? "New test (regenerates)" : "Take chapter test"}
              </button>
            )
          )}
          {startError && <p className="text-xs text-red-600 dark:text-red-400">{startError}</p>}
        </div>

        <div className="flex flex-col gap-2">
          <h2 className="text-base font-semibold">Test history</h2>
          {tests === null && (
            <p role="status" className="text-sm text-muted-foreground">
              Loading tests…
            </p>
          )}
          {retakeError && <p className="text-xs text-red-600 dark:text-red-400">{retakeError}</p>}
          {tests !== null && tests.length > 0 && (
            <ul className="flex flex-col gap-3">
              {tests.map((test) => (
                <li key={test.id} className="rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium">
                      {new Date(test.created_at).toLocaleDateString()} · {test.question_count}{" "}
                      questions
                    </span>
                    <button
                      type="button"
                      onClick={() => void handleRetake(test.id)}
                      disabled={retakingTestId === test.id}
                      title="Same questions, no generation cost"
                      className="shrink-0 rounded-md border border-border px-2 py-1 text-xs font-medium disabled:opacity-50"
                    >
                      Retake
                    </button>
                  </div>
                  <ul className="mt-2 flex flex-col gap-1">
                    {test.attempts.map((attempt) => (
                      <li key={attempt.id}>
                        <Link
                          href={`/course/${courseId}/test/${attempt.id}`}
                          className="flex w-full items-center justify-between rounded px-2 py-1.5 text-sm hover:bg-muted-foreground/10"
                        >
                          <span>{new Date(attempt.created_at).toLocaleDateString()}</span>
                          <span className="text-muted-foreground">
                            {attempt.score !== null
                              ? `${Math.round(attempt.score * 100)}%`
                              : "In progress"}
                          </span>
                        </Link>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
