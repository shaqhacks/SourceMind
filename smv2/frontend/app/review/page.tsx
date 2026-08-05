"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";

import ErrorBanner from "@/components/ErrorBanner";
import Markdown from "@/components/Markdown";
import ShortcutsOverlay, { type ShortcutHint } from "@/components/ShortcutsOverlay";
import Badge, { type BadgeTone } from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import EmptyState from "@/components/ui/EmptyState";
import ProgressBar from "@/components/ui/ProgressBar";
import Skeleton from "@/components/ui/Skeleton";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  getReviewQueue,
  getAdaptiveStudyQueue,
  getReviewSummary,
  gradeCard,
  submitPracticeAnswer,
  MAX_QUEUE_FETCH,
  type ReviewQueueCardOut,
  type ReviewSummaryOut,
  type AdaptiveStudyActivityOut,
  type SubmitPracticeAnswerOut,
} from "@/lib/api/client";
import { useKeyboardShortcuts, type ShortcutMap } from "@/lib/hooks/useKeyboardShortcuts";
import { useRouteFocus } from "@/lib/hooks/useRouteFocus";
import { formatIntervalPreview, previewIntervalDays, type ReviewGrade } from "@/lib/review/intervalPreview";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

const SHORTCUT_HINTS: ShortcutHint[] = [
  { keys: "space", description: "Reveal answer" },
  { keys: "1 2 3 4", description: "Grade: Again / Hard / Good / Easy" },
  { keys: "?", description: "Show this help" },
];

const GRADE_LABELS: Record<number, string> = { 1: "Again", 2: "Hard", 3: "Good", 4: "Easy" };
const GRADE_TONES: Record<number, BadgeTone> = { 1: "serious", 2: "warning", 3: "good", 4: "accent" };
// Organic system: attention ramp for the two "didn't stick" grades, sage
// ramp for the two "stuck" grades — see the redesign handoff §4.
const GRADE_BUTTON_BG: Record<number, string> = {
  1: "bg-accent-200",
  2: "bg-accent-100",
  3: "bg-sage-200",
  4: "bg-sage-300",
};
const REVIEW_SESSION_STORAGE_KEY = "smv2.review.session";

interface StoredReviewSession {
  courseId: string | null;
  chosenSize: number;
  remainingCardIds: string[];
  gradedTally: Record<number, number>;
  startedAt: number;
}

function isStoredReviewSession(value: unknown): value is StoredReviewSession {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    (typeof v.courseId === "string" || v.courseId === null) &&
    typeof v.chosenSize === "number" &&
    Array.isArray(v.remainingCardIds) &&
    v.remainingCardIds.every((id) => typeof id === "string") &&
    typeof v.gradedTally === "object" &&
    v.gradedTally !== null &&
    typeof v.startedAt === "number"
  );
}

function readStoredSession(): StoredReviewSession | null {
  try {
    const raw = window.localStorage.getItem(REVIEW_SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isStoredReviewSession(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function writeStoredSession(session: StoredReviewSession): void {
  try {
    window.localStorage.setItem(REVIEW_SESSION_STORAGE_KEY, JSON.stringify(session));
  } catch {
    // localStorage unavailable/full — resume is a nicety, not critical;
    // fail silently rather than breaking the review flow over it.
  }
}

function clearStoredSession(): void {
  try {
    window.localStorage.removeItem(REVIEW_SESSION_STORAGE_KEY);
  } catch {
    // ignore
  }
}

type HubState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "ready"; summary: ReviewSummaryOut };

type ChooserState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "ready"; due: number; new: number; total: number };

type SessionState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "empty" }
  | { kind: "active" }
  | { kind: "done" };

function courseOverdueCount(course: ReviewSummaryOut["courses"][number]): number {
  return course.overdue_count ?? 0;
}

function courseAvailableCount(course: ReviewSummaryOut["courses"][number]): number {
  return course.available_count ?? course.total_count ?? courseOverdueCount(course) + course.new_count;
}

function summaryOverdueCount(summary: ReviewSummaryOut): number {
  return summary.courses.reduce((total, course) => total + courseOverdueCount(course), 0);
}

function summaryAvailableCount(summary: ReviewSummaryOut): number {
  return summary.courses.reduce((total, course) => total + courseAvailableCount(course), 0);
}

function ReviewPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const courseParam = searchParams.get("course");
  const startParam = searchParams.get("start");

  // "resuming" is a brief transitional phase, only entered when a saved
  // session exists at mount: it reconciles remainingCardIds against a
  // fresh queue fetch (cards graded elsewhere meanwhile have already
  // dropped server-side) before deciding whether there's really
  // something to resume into.
  //
  // "bootstrapping-due" is a separate, higher-priority entry point: an
  // explicit ?start=due (e.g. the post-test "Start review" CTA, or the
  // dashboard's Review card) is a fresh, deliberate intent to review
  // what's due right now for a specific course — it bypasses hub/chooser
  // entirely and takes priority over resuming a stale saved session,
  // which gets silently superseded rather than restored.
  const [phase, setPhase] = useState<
    "hub" | "chooser" | "session" | "resuming" | "bootstrapping-due"
  >(() => {
    if (courseParam && startParam === "due") return "bootstrapping-due";
    return readStoredSession() ? "resuming" : courseParam ? "chooser" : "hub";
  });
  const [courseId, setCourseId] = useState<string | null>(courseParam);
  // Only ever populated from the hub's already-loaded ReviewSummaryOut (see
  // goToChooser) — a direct ?course= deep link, a resumed session, or a
  // ?start=due bootstrap has no course title in hand and none is fetched
  // for it, so the header falls back to the untitled "Review session".
  const [courseTitle, setCourseTitle] = useState<string | null>(null);
  const [hubState, setHubState] = useState<HubState>({ kind: "loading" });
  const [chooserState, setChooserState] = useState<ChooserState>({ kind: "loading" });
  const [sessionState, setSessionState] = useState<SessionState>({ kind: "loading" });
  const [sessionSize, setSessionSize] = useState<number | null>(null);
  const [sessionStartedAt, setSessionStartedAt] = useState(0);
  const [isResumedSession, setIsResumedSession] = useState(false);
  const [cards, setCards] = useState<ReviewQueueCardOut[]>([]);
  const [questions, setQuestions] = useState<AdaptiveStudyActivityOut[]>([]);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [selectedChoice, setSelectedChoice] = useState<number | null>(null);
  const [questionResult, setQuestionResult] = useState<SubmitPracticeAnswerOut | null>(null);
  const [cardIndex, setCardIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [cardShownAt, setCardShownAt] = useState(0);
  const [gradeCounts, setGradeCounts] = useState<Record<number, number>>({});
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useRouteFocus(headingRef);

  // Runs once, only when mount found a saved session: reconcile it
  // against a fresh queue fetch and either drop straight into the
  // session (skipping hub/chooser) or fall back to the normal flow if
  // nothing's left to resume (all graded elsewhere, or the fetch failed).
  useEffect(() => {
    if (phase !== "resuming") return;
    let active = true;

    async function reconcile() {
      const stored = readStoredSession();
      if (!stored || !stored.courseId || stored.remainingCardIds.length === 0) {
        clearStoredSession();
        if (active) setPhase(courseParam ? "chooser" : "hub");
        return;
      }
      const storedCourseId = stored.courseId;
      if (active) setCourseId(storedCourseId);

      const { data } = await getReviewQueue(storedCourseId, MAX_QUEUE_FETCH);
      if (!active) return;
      if (!data) {
        // Couldn't reconcile (network) — don't lose the session over a
        // transient failure; land on the chooser instead of silently
        // discarding it.
        setPhase("chooser");
        return;
      }
      const byId = new Map(data.cards.map((card) => [card.id, card]));
      const reconciled = stored.remainingCardIds
        .map((id) => byId.get(id))
        .filter((card): card is ReviewQueueCardOut => card !== undefined);
      if (reconciled.length === 0) {
        clearStoredSession();
        setPhase("chooser");
        return;
      }
      setCards(reconciled);
      setCardIndex(0);
      setRevealed(false);
      setCardShownAt(Date.now());
      setGradeCounts(stored.gradedTally);
      setSessionSize(stored.chosenSize);
      setSessionStartedAt(stored.startedAt);
      setIsResumedSession(true);
      setSessionState({ kind: "active" });
      setPhase("session");
    }

    void reconcile();
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase]);

  const loadHub = useCallback(() => {
    setHubState({ kind: "loading" });
    getReviewSummary().then(({ data, status }) => {
      if (data) setHubState({ kind: "ready", summary: data });
      else setHubState({ kind: "error", error: describeError(status, "Loading review summary") });
    });
  }, []);

  useEffect(() => {
    if (phase !== "hub") return;
    let active = true;
    getReviewSummary().then(({ data, status }) => {
      if (!active) return;
      if (data) setHubState({ kind: "ready", summary: data });
      else setHubState({ kind: "error", error: describeError(status, "Loading review summary") });
    });
    return () => {
      active = false;
    };
  }, [phase]);

  const loadChooser = useCallback((id: string) => {
    setChooserState({ kind: "loading" });
    Promise.all([getReviewQueue(id, MAX_QUEUE_FETCH), getAdaptiveStudyQueue(id, MAX_QUEUE_FETCH)]).then(([review, adaptive]) => {
      if (review.data) {
        const questionCount = adaptive.data?.activities.filter((item) => item.activity_type === "question").length ?? 0;
        setChooserState({ kind: "ready", due: review.data.due, new: review.data.new, total: review.data.total + questionCount });
      } else {
        setChooserState({ kind: "error", error: describeError(review.status, "Loading review queue") });
      }
    });
  }, []);

  useEffect(() => {
    if (phase !== "chooser" || !courseId) return;
    let active = true;
    Promise.all([getReviewQueue(courseId, MAX_QUEUE_FETCH), getAdaptiveStudyQueue(courseId, MAX_QUEUE_FETCH)]).then(([review, adaptive]) => {
      if (!active) return;
      if (review.data) {
        const questionCount = adaptive.data?.activities.filter((item) => item.activity_type === "question").length ?? 0;
        setChooserState({ kind: "ready", due: review.data.due, new: review.data.new, total: review.data.total + questionCount });
      } else {
        setChooserState({ kind: "error", error: describeError(review.status, "Loading review queue") });
      }
    });
    return () => {
      active = false;
    };
  }, [phase, courseId]);

  function goToChooser(id: string, title: string) {
    setCourseId(id);
    setCourseTitle(title);
    setPhase("chooser");
    router.push(`/review?course=${id}`);
  }

  const startSession = useCallback(
    (size: number) => {
      if (!courseId) return;
      setPhase("session");
      setSessionState({ kind: "loading" });
      setSessionSize(size);
      setGradeCounts({});
      setIsResumedSession(false);
      Promise.all([getReviewQueue(courseId, size), getAdaptiveStudyQueue(courseId, size)]).then(([review, adaptive]) => {
        if (!review.data) {
          setSessionState({ kind: "error", error: describeError(review.status, "Loading review queue") });
          return;
        }
        const questionActivities = adaptive.data?.activities.filter((item) => item.activity_type === "question") ?? [];
        if (review.data.cards.length === 0 && questionActivities.length === 0) {
          setSessionState({ kind: "empty" });
          return;
        }
        const startedAt = Date.now();
        setCards(review.data.cards);
        setQuestions(questionActivities);
        setQuestionIndex(0);
        setSelectedChoice(null);
        setQuestionResult(null);
        setCardIndex(0);
        setRevealed(false);
        setCardShownAt(startedAt);
        setSessionStartedAt(startedAt);
        writeStoredSession({
          courseId,
          chosenSize: size,
          remainingCardIds: review.data.cards.map((card) => card.id),
          gradedTally: {},
          startedAt,
        });
        setSessionState({ kind: "active" });
      });
    },
    [courseId],
  );

  // Runs once when the URL says start=due: discard whatever saved session
  // was left over (a deliberate supersede, not a bug to guard against),
  // look up how many cards are due right now, and kick off a session sized
  // to exactly that — reusing startSession's own plumbing (localStorage
  // write, phase transition) rather than duplicating it. Falls back to the
  // chooser if the lookup fails or nothing is actually due.
  useEffect(() => {
    if (phase !== "bootstrapping-due" || !courseId) return;
    clearStoredSession();
    let active = true;
    getReviewQueue(courseId, MAX_QUEUE_FETCH).then(({ data, status }) => {
      if (!active) return;
      if (!data) {
        setChooserState({ kind: "error", error: describeError(status, "Loading review queue") });
        setPhase("chooser");
        return;
      }
      if (data.due === 0) {
        setChooserState({ kind: "ready", due: data.due, new: data.new, total: data.total });
        setPhase("chooser");
        return;
      }
      startSession(data.due);
    });
    return () => {
      active = false;
    };
  }, [phase, courseId, startSession]);

  const discardResumedSession = useCallback(() => {
    clearStoredSession();
    setIsResumedSession(false);
    setCards([]);
    setCardIndex(0);
    setGradeCounts({});
    setSessionState({ kind: "loading" });
    setPhase("chooser");
  }, []);

  const reveal = useCallback(() => setRevealed(true), []);

  const grade = useCallback(
    (value: number) => {
      const card = cards[cardIndex];
      if (!card) return;
      const elapsedMs = Date.now() - cardShownAt;
      const nextTally = { ...gradeCounts, [value]: (gradeCounts[value] ?? 0) + 1 };
      setGradeCounts(nextTally);
      // Fire-and-forget: grading must feel instant (keyboard-first is the
      // law here), not wait on a network round trip before the next card.
      void gradeCard(card.id, { grade: value, elapsed_ms: elapsedMs });
      notifyReviewSettled();

      const nextIndex = cardIndex + 1;
      if (nextIndex >= cards.length) {
        clearStoredSession();
        if (questions.length === 0) setSessionState({ kind: "done" });
        else setCardIndex(nextIndex);
      } else {
        if (courseId && sessionSize !== null) {
          writeStoredSession({
            courseId,
            chosenSize: sessionSize,
            remainingCardIds: cards.slice(nextIndex).map((c) => c.id),
            gradedTally: nextTally,
            startedAt: sessionStartedAt,
          });
        }
        setCardIndex(nextIndex);
        setRevealed(false);
        setCardShownAt(Date.now());
      }
    },
    [cards, cardIndex, cardShownAt, courseId, sessionSize, sessionStartedAt, gradeCounts, questions.length],
  );

  const answerQuestion = useCallback(async (choice: number) => {
    const question = questions[questionIndex];
    if (!question || !courseId || questionResult) return;
    setSelectedChoice(choice);
    const { data } = await submitPracticeAnswer(courseId, question.activity_id, choice);
    if (data) setQuestionResult(data);
  }, [courseId, questionIndex, questionResult, questions]);

  const advanceQuestion = useCallback(() => {
    const next = questionIndex + 1;
    if (next >= questions.length) {
      setSessionState({ kind: "done" });
      return;
    }
    setQuestionIndex(next);
    setSelectedChoice(null);
    setQuestionResult(null);
  }, [questionIndex, questions.length]);

  const openShortcuts = useCallback(() => setShortcutsOpen(true), []);
  const closeShortcuts = useCallback(() => setShortcutsOpen(false), []);

  const shortcutMap: ShortcutMap =
    phase === "session" && sessionState.kind === "active" && cards[cardIndex]
      ? revealed
        ? {
            "1": () => grade(1),
            "2": () => grade(2),
            "3": () => grade(3),
            "4": () => grade(4),
            "?": openShortcuts,
          }
        : { " ": reveal, "?": openShortcuts }
      : { "?": openShortcuts };

  useKeyboardShortcuts(shortcutMap);

  let mainContent: React.ReactNode;

  if (phase === "resuming") {
    mainContent = (
      <p role="status" className="p-8 text-sm text-muted-foreground">
        Checking for an unfinished session…
      </p>
    );
  } else if (phase === "bootstrapping-due") {
    mainContent = (
      <p role="status" className="p-8 text-sm text-muted-foreground">
        Starting your review…
      </p>
    );
  } else if (phase === "hub") {
    if (hubState.kind === "loading") {
      mainContent = (
        <div role="status" className="p-8">
          <span className="sr-only">Loading…</span>
          <Skeleton className="mx-auto mt-8 h-40 w-full max-w-2xl" />
        </div>
      );
    } else if (hubState.kind === "error") {
      mainContent = (
        <div className="p-8">
          <ErrorBanner
            status={hubState.error.status}
            message={hubState.error.message}
            onRetry={loadHub}
          />
        </div>
      );
    } else if (summaryAvailableCount(hubState.summary) === 0) {
      mainContent = (
        <div className="flex flex-1 items-center justify-center p-8">
          <EmptyState
            icon="✨"
            title="All caught up"
            body="Generate flashcards from a chapter, or keep reading."
          />
        </div>
      );
    } else {
      const { summary } = hubState;
      mainContent = (
        <div className="mx-auto flex w-full max-w-2xl flex-col gap-4 p-8">
          <h2 className="text-lg font-semibold">Review</h2>
          {summary.backlog_warning && (
            <div
              role="alert"
              className="rounded-md border border-accent/40 bg-accent-soft px-4 py-3 text-sm text-accent-800"
            >
              {summaryOverdueCount(summary)} overdue — more than 2 days at your pace.
            </div>
          )}
          <ul className="flex flex-col gap-2">
            {summary.courses.map((course) => (
              <li key={course.course_id}>
                <Card interactive>
                  <button
                    type="button"
                    onClick={() => goToChooser(course.course_id, course.title)}
                    className="flex w-full items-center justify-between text-left text-sm"
                  >
                    <span className="font-medium">{course.title}</span>
                    <span className="text-muted-foreground">
                      {courseOverdueCount(course)} overdue · {course.new_count} new
                    </span>
                  </button>
                </Card>
              </li>
            ))}
          </ul>
        </div>
      );
    }
  } else if (phase === "chooser") {
    if (chooserState.kind === "loading") {
      mainContent = (
        <div role="status" className="p-8">
          <span className="sr-only">Loading…</span>
          <Skeleton className="mx-auto mt-8 h-40 w-full max-w-2xl" />
        </div>
      );
    } else if (chooserState.kind === "error") {
      mainContent = (
        <div className="p-8">
          <ErrorBanner
            status={chooserState.error.status}
            message={chooserState.error.message}
            onRetry={() => courseId && loadChooser(courseId)}
          />
        </div>
      );
    } else if (chooserState.total === 0) {
      mainContent = (
        <div className="flex flex-1 items-center justify-center p-8">
          <EmptyState
            icon="✨"
            title="All caught up"
            body="Generate flashcards from a chapter, or keep reading."
          />
        </div>
      );
    } else {
      const { total, due, new: newCount } = chooserState;
      const sizeOptions: { label: string; value: number }[] = [];
      if (total > 10) sizeOptions.push({ label: "10", value: 10 });
      if (total > 25) sizeOptions.push({ label: "25", value: 25 });
      sizeOptions.push({ label: `All (${total})`, value: total });

      mainContent = (
        <div className="mx-auto flex w-full max-w-md flex-col items-center gap-4 p-8 text-center">
          <h2 className="text-lg font-semibold">Ready to review</h2>
          <p className="text-sm text-muted-foreground">
            {due} due · {newCount} new
          </p>
          <div className="flex gap-3">
            {sizeOptions.map((option) => (
              <Button key={option.value} variant="primary" onClick={() => startSession(option.value)}>
                Review {option.label}
              </Button>
            ))}
          </div>
        </div>
      );
    }
  } else if (sessionState.kind === "loading") {
    mainContent = (
      <div role="status" className="p-8">
        <span className="sr-only">Loading…</span>
        <Skeleton className="mx-auto mt-8 h-40 w-full max-w-2xl" />
      </div>
    );
  } else if (sessionState.kind === "error") {
    mainContent = (
      <div className="p-8">
        <ErrorBanner
          status={sessionState.error.status}
          message={sessionState.error.message}
          onRetry={() => sessionSize && startSession(sessionSize)}
        />
      </div>
    );
  } else if (sessionState.kind === "empty") {
    mainContent = (
      <div className="flex flex-1 items-center justify-center p-8">
        <EmptyState
          icon="✨"
          title="All caught up"
          body="Generate flashcards from a chapter, or keep reading."
        />
      </div>
    );
  } else if (sessionState.kind === "done") {
    mainContent = (
      <div className="mx-auto flex w-full max-w-md flex-col items-center gap-4 p-8 text-center">
        <h2 className="text-lg font-semibold">Session complete</h2>
        <ul className="flex flex-col gap-2">
          {[1, 2, 3, 4].map((value) => (
            <li key={value}>
              <Badge tone={GRADE_TONES[value]}>
                {GRADE_LABELS[value]}: {gradeCounts[value] ?? 0}
              </Badge>
            </li>
          ))}
        </ul>
        <Link href="/review" className="text-sm font-medium text-accent underline">
          Back to review
        </Link>
      </div>
    );
  } else {
    const card = cards[cardIndex];
    const question = card ? null : questions[questionIndex];
    const totalActivities = cards.length + questions.length;
    const currentActivity = card ? cardIndex + 1 : cards.length + questionIndex + 1;
    mainContent = (
      <div className="mx-auto flex w-full max-w-[760px] flex-1 flex-col gap-6 px-9 py-10">
        {isResumedSession && (
          <div
            role="status"
            className="flex items-center justify-between gap-3 rounded-md border border-divider bg-accent-soft px-4 py-2 text-sm"
          >
            <span>
              Resumed session — {cards.length - cardIndex} left
            </span>
            <button
              type="button"
              onClick={discardResumedSession}
              className="shrink-0 rounded-md border border-divider px-2 py-1 text-xs font-medium"
            >
              Discard
            </button>
          </div>
        )}

        <div className="flex items-center gap-3.5">
          <div className="flex-1">
            <ProgressBar
              percent={(currentActivity / totalActivities) * 100}
              label={`${currentActivity} of ${totalActivities}`}
              tone="accent"
            />
          </div>
          <p role="status" className="shrink-0 text-sm font-semibold text-muted-foreground">
            {currentActivity} of {totalActivities}
          </p>
        </div>

        {card ? <><Card className="flex min-h-[320px] flex-col p-10 shadow-md">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-accent">
            Spaced repetition
          </span>
          <div className="mt-3.5 font-heading text-2xl leading-snug">
            <Markdown>{card.front_md}</Markdown>
          </div>
          {revealed && (
            <div className="mt-7 border-t border-divider pt-6 text-[17px] leading-relaxed">
              <Markdown>{card.back_md}</Markdown>
            </div>
          )}
          <div className="mt-auto flex flex-wrap items-center gap-2 pt-6">
            {card.is_new && <Badge tone="neutral">New card</Badge>}
            <Link
              href={`/course/${courseId}?section=${card.section_id}`}
              className="ml-auto text-xs font-medium text-accent hover:underline"
            >
              Open in chapter →
            </Link>
          </div>
        </Card>

        {!revealed ? (
          <Button variant="primary" size="md" onClick={reveal} className="self-center px-6">
            Reveal (space)
          </Button>
        ) : (
          <div className="grid grid-cols-4 gap-3">
            {([1, 2, 3, 4] as ReviewGrade[]).map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => grade(value)}
                aria-label={`${GRADE_LABELS[value]} (${value})`}
                className={`flex flex-col items-center gap-1 rounded-md py-3 text-foreground transition-opacity hover:opacity-80 ${GRADE_BUTTON_BG[value]}`}
              >
                <span aria-hidden="true" className="text-[15px] font-semibold">
                  {GRADE_LABELS[value]}
                </span>
                <span aria-hidden="true" className="font-mono text-[11px] opacity-70">
                  {value} ·{" "}
                  {formatIntervalPreview(
                    previewIntervalDays(value, {
                      intervalDays: card.interval_days,
                      ease: card.ease,
                      reps: card.reps,
                    }),
                  )}
                </span>
              </button>
            ))}
          </div>
        )}</> : question ? (
          <Card className="flex min-h-[320px] flex-col gap-4 p-10 shadow-md">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-accent">
              Concept practice · {question.readiness_state.replaceAll("_", " ")}
            </span>
            <div className="font-heading text-2xl leading-snug">
              <Markdown>{String(question.payload.stem_md ?? "")}</Markdown>
            </div>
            <div className="grid gap-2">
              {(Array.isArray(question.payload.choices) ? question.payload.choices : []).map((choice, index) => (
                <button
                  key={`${question.activity_id}-${index}`}
                  type="button"
                  disabled={questionResult !== null}
                  onClick={() => void answerQuestion(index)}
                  className="rounded-md border border-divider px-4 py-3 text-left text-sm hover:bg-accent-soft disabled:cursor-default"
                >
                  {String(choice)}
                </button>
              ))}
            </div>
            {questionResult && (
              <div role="status" className="rounded-md bg-surface-raised p-4 text-sm">
                <strong>{questionResult.correct ? "Correct" : "Not yet"}.</strong>{" "}
                {questionResult.explanation_md}
                <Button variant="primary" size="sm" onClick={advanceQuestion} className="mt-3">
                  {questionIndex + 1 >= questions.length ? "Finish" : "Next question"}
                </Button>
              </div>
            )}
            {selectedChoice !== null && !questionResult && (
              <p className="text-sm text-muted-foreground">Checking answer…</p>
            )}
          </Card>
        ) : null}

        <p className="text-center text-xs text-muted-foreground">
          {(card ? SHORTCUT_HINTS : SHORTCUT_HINTS.filter((hint) => hint.keys === "?")).map((hint, i) => (
            <span key={hint.keys}>
              {i > 0 ? " · " : null}
              <kbd className="rounded border border-divider bg-surface-raised px-1.5 text-xs">
                {hint.keys}
              </kbd>{" "}
              {hint.description}
            </span>
          ))}
        </p>
      </div>
    );
  }

  const sessionActive = phase === "session" || phase === "resuming" || phase === "bootstrapping-due";
  const headerLabel = courseId ? (courseTitle ? `Review session · ${courseTitle}` : "Review session") : "Review";

  const endSession = () => {
    clearStoredSession();
    router.push("/");
  };

  return (
    <>
      <div className="flex items-center gap-3 border-b border-divider px-5 py-3">
        <Link
          href="/"
          aria-label="Back home"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-surface-raised transition-colors hover:bg-foreground/[0.07]"
        >
          <ArrowLeft aria-hidden="true" className="h-4 w-4" strokeWidth={2.75} />
        </Link>
        <h1 ref={headingRef} tabIndex={-1} className="truncate text-sm font-medium outline-none">
          {headerLabel}
        </h1>
        {sessionActive && (
          <Button variant="secondary" size="sm" onClick={endSession} className="ml-auto shrink-0">
            End session
          </Button>
        )}
      </div>
      {mainContent}
      <ShortcutsOverlay open={shortcutsOpen} onClose={closeShortcuts} shortcuts={SHORTCUT_HINTS} />
    </>
  );
}

// /review has no dynamic route segment, so Next.js tries to statically
// prerender it at build time — and useSearchParams() (used above, for
// ?course=) requires a Suspense boundary in that case, or the build fails.
export default function ReviewPage() {
  return (
    <Suspense
      fallback={
        <p role="status" className="p-8 text-sm text-muted-foreground">
          Loading…
        </p>
      }
    >
      <ReviewPageInner />
    </Suspense>
  );
}
