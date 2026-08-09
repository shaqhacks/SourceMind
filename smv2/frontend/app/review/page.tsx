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
import ReviewGradeControls, {
  type ReviewGradeRequest,
} from "@/components/review/ReviewGradeControls";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  getReviewQueue,
  getReviewSelection,
  getAdaptiveStudyQueue,
  getReviewSummary,
  submitPracticeAnswer,
  MAX_QUEUE_FETCH,
  type ReviewQueueCardOut,
  type ReviewSummaryOut,
  type AdaptiveStudyActivityOut,
  type SubmitPracticeAnswerOut,
} from "@/lib/api/client";
import { useKeyboardShortcuts, type ShortcutMap } from "@/lib/hooks/useKeyboardShortcuts";
import { useRouteFocus } from "@/lib/hooks/useRouteFocus";
import type { ReviewGrade } from "@/lib/review/intervalPreview";
import {
  clearActiveReviewSession,
  readActiveReviewSession,
  readCompletedReviewSession,
  writeActiveReviewSession,
  writeCompletedReviewSession,
  type ActiveReviewSession,
  type CompletedReviewSession,
  type ReviewScope,
} from "@/lib/review/sessionStorage";

const SHORTCUT_HINTS: ShortcutHint[] = [
  { keys: "space", description: "Reveal answer" },
  { keys: "1 2 3 4", description: "Grade: Again / Hard / Good / Easy" },
  { keys: "?", description: "Show this help" },
];

const GRADE_LABELS: Record<number, string> = { 1: "Again", 2: "Hard", 3: "Good", 4: "Easy" };
const GRADE_TONES: Record<number, BadgeTone> = { 1: "serious", 2: "warning", 3: "good", 4: "accent" };
function isReviewScope(value: string | null): value is ReviewScope {
  return value === "available" || value === "all" || value === "needs_attention";
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
  return course.overdue_count;
}

function courseAvailableCount(course: ReviewSummaryOut["courses"][number]): number {
  return course.available_count;
}

function summaryOverdueCount(summary: ReviewSummaryOut): number {
  return summary.courses.reduce((total, course) => total + courseOverdueCount(course), 0);
}

function summaryAvailableCount(summary: ReviewSummaryOut): number {
  return summary.courses.reduce((total, course) => total + courseAvailableCount(course), 0);
}

function queueMetrics(
  queue: { cards: ReviewQueueCardOut[]; overdue_count: number; new_count: number; available_count: number },
  questionCount: number,
  chapterLabel?: string,
) {
  if (!chapterLabel) {
    return {
      due: queue.overdue_count,
      new: queue.new_count,
      total: queue.available_count + questionCount,
    };
  }
  return {
    due: queue.cards.filter((card) => card.is_due).length,
    new: queue.cards.filter((card) => card.is_new).length,
    total: queue.cards.length,
  };
}

function newSessionId(): string {
  return `review-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function activeReviewUrl(courseId: string, scope: ReviewScope, chapterLabel: string | null): string {
  const params = new URLSearchParams({ course: courseId });
  if (scope !== "available") params.set("scope", scope);
  if (chapterLabel) params.set("chapter", chapterLabel);
  return `/review?${params.toString()}`;
}

function shouldResumeActiveReviewSession(
  session: ActiveReviewSession | null,
  courseId: string | null,
  scope: ReviewScope | undefined,
  chapterLabel: string | undefined,
): session is ActiveReviewSession {
  if (!session) return false;
  if (!courseId) return true;
  return (
    session.courseId === courseId &&
    session.scope === (scope ?? "available") &&
    session.chapterLabel === (chapterLabel ?? null)
  );
}

function ReviewPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const courseParam = searchParams.get("course");
  const startParam = searchParams.get("start");
  const scopeParam = searchParams.get("scope");
  const completedParam = searchParams.get("completed");
  const reviewScope = isReviewScope(scopeParam) ? scopeParam : undefined;
  const chapterLabel = searchParams.get("chapter") ?? undefined;
  const queryKey = searchParams.toString();
  const hasExplicitSessionQuery = Boolean(startParam || completedParam || scopeParam || chapterLabel);

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
    "hub" | "chooser" | "session" | "resuming" | "bootstrapping-due" | "completed"
  >(() => {
    if (courseParam && completedParam) return "completed";
    if (courseParam && startParam === "due") return "bootstrapping-due";
    return shouldResumeActiveReviewSession(readActiveReviewSession(), courseParam, reviewScope, chapterLabel)
      ? "resuming"
      : courseParam
        ? "chooser"
        : "hub";
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
  const [gradeRequest, setGradeRequest] = useState<ReviewGradeRequest | null>(null);
  const [gradePending, setGradePending] = useState(false);
  const [gradeCounts, setGradeCounts] = useState<Record<number, number>>({});
  const [againCardIds, setAgainCardIds] = useState<string[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [completedSession, setCompletedSession] = useState<CompletedReviewSession | null>(() => {
    if (!courseParam || !completedParam) return null;
    const stored = readCompletedReviewSession();
    return stored && stored.courseId === courseParam && stored.sessionId === completedParam ? stored : null;
  });
  const [replayMissingMessage, setReplayMissingMessage] = useState<string | null>(null);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const reconciledQueryRef = useRef(queryKey);
  const bootstrappedQueryRef = useRef<string | null>(null);
  const replayRequestTokenRef = useRef(0);
  const latestQueryRef = useRef({ courseParam, completedParam, queryKey });
  useRouteFocus(headingRef);

  useEffect(() => {
    latestQueryRef.current = { courseParam, completedParam, queryKey };
  }, [courseParam, completedParam, queryKey]);

  useEffect(() => {
    if (reconciledQueryRef.current === queryKey) return;
    reconciledQueryRef.current = queryKey;
    let active = true;

    queueMicrotask(() => {
      if (!active) return;
      setCourseId(courseParam);
      setReplayMissingMessage(null);

      if (courseParam && completedParam) {
        const stored = readCompletedReviewSession();
        setCompletedSession(
          stored && stored.courseId === courseParam && stored.sessionId === completedParam ? stored : null,
        );
        setSessionState({ kind: "done" });
        setPhase("completed");
        return;
      }

      setCompletedSession(null);
      if (courseParam && startParam === "due") {
        setPhase("bootstrapping-due");
        return;
      }

      if (courseParam) {
        if (shouldResumeActiveReviewSession(readActiveReviewSession(), courseParam, reviewScope, chapterLabel)) {
          setPhase("resuming");
          return;
        }
        if (hasExplicitSessionQuery) clearActiveReviewSession();
        setChooserState({ kind: "loading" });
        setPhase("chooser");
        return;
      }

      if (!hasExplicitSessionQuery && shouldResumeActiveReviewSession(readActiveReviewSession(), null, undefined, undefined)) {
        setPhase("resuming");
        return;
      }

      setPhase("hub");
    });

    return () => {
      active = false;
    };
  }, [queryKey, courseParam, completedParam, startParam, hasExplicitSessionQuery, reviewScope, chapterLabel]);

  // Runs once, only when mount found a saved session: reconcile it
  // against a fresh queue fetch and either drop straight into the
  // session (skipping hub/chooser) or fall back to the normal flow if
  // nothing's left to resume (all graded elsewhere, or the fetch failed).
  useEffect(() => {
    if (phase !== "resuming") return;
    let active = true;

    async function reconcile() {
      const stored = readActiveReviewSession();
      if (!stored || !stored.courseId || stored.remainingCardIds.length === 0) {
        clearActiveReviewSession();
        if (active) setPhase(courseParam ? "chooser" : "hub");
        return;
      }
      const storedCourseId = stored.courseId;
      if (active) setCourseId(storedCourseId);

      const { data } = await getReviewQueue(storedCourseId, { limit: MAX_QUEUE_FETCH });
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
        clearActiveReviewSession();
        setPhase("chooser");
        return;
      }
      setCards(reconciled);
      setCardIndex(0);
      setRevealed(false);
      setGradeCounts(stored.gradedTally);
      setAgainCardIds(stored.againCardIds);
      setActiveSessionId(stored.sessionId);
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
    Promise.all([
      getReviewQueue(id, { limit: MAX_QUEUE_FETCH, scope: reviewScope, chapterLabel }),
      getAdaptiveStudyQueue(id, MAX_QUEUE_FETCH),
    ]).then(([review, adaptive]) => {
      if (review.data) {
        const questionCount = adaptive.data?.activities.filter((item) => item.activity_type === "question").length ?? 0;
        const metrics = queueMetrics(review.data, questionCount, chapterLabel);
        setChooserState({
          kind: "ready",
          due: metrics.due,
          new: metrics.new,
          total: metrics.total,
        });
      } else {
        setChooserState({ kind: "error", error: describeError(review.status, "Loading review queue") });
      }
    });
  }, [chapterLabel, reviewScope]);

  useEffect(() => {
    if (phase !== "chooser" || !courseId) return;
    let active = true;
    Promise.all([
      getReviewQueue(courseId, { limit: MAX_QUEUE_FETCH, scope: reviewScope, chapterLabel }),
      getAdaptiveStudyQueue(courseId, MAX_QUEUE_FETCH),
    ]).then(([review, adaptive]) => {
      if (!active) return;
      if (review.data) {
        const questionCount = adaptive.data?.activities.filter((item) => item.activity_type === "question").length ?? 0;
        const metrics = queueMetrics(review.data, questionCount, chapterLabel);
        setChooserState({
          kind: "ready",
          due: metrics.due,
          new: metrics.new,
          total: metrics.total,
        });
      } else {
        setChooserState({ kind: "error", error: describeError(review.status, "Loading review queue") });
      }
    });
    return () => {
      active = false;
    };
  }, [phase, courseId, chapterLabel, reviewScope]);

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
      Promise.all([
        getReviewQueue(courseId, { limit: size, scope: reviewScope, chapterLabel }),
        getAdaptiveStudyQueue(courseId, size),
      ]).then(([review, adaptive]) => {
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
        setGradeRequest(null);
        setGradePending(false);
        setSessionStartedAt(startedAt);
        const sessionId = newSessionId();
        setActiveSessionId(sessionId);
        setAgainCardIds([]);
        writeActiveReviewSession({
          version: 1,
          sessionId,
          courseId,
          scope: reviewScope ?? "available",
          chapterLabel: chapterLabel ?? null,
          chosenSize: size,
          remainingCardIds: review.data.cards.map((card) => card.id),
          gradedTally: {},
          againCardIds: [],
          startedAt,
        });
        setSessionState({ kind: "active" });
      });
    },
    [chapterLabel, courseId, reviewScope],
  );

  // Runs once when the URL says start=due: discard whatever saved session
  // was left over (a deliberate supersede, not a bug to guard against),
  // look up how many cards are due right now, and kick off a session sized
  // to exactly that — reusing startSession's own plumbing (localStorage
  // write, phase transition) rather than duplicating it. Falls back to the
  // chooser if the lookup fails or nothing is actually due.
  useEffect(() => {
    if (phase !== "bootstrapping-due" || !courseId) return;
    if (bootstrappedQueryRef.current === queryKey) return;
    bootstrappedQueryRef.current = queryKey;
    clearActiveReviewSession();
    let active = true;
    Promise.all([
      getReviewQueue(courseId, { limit: MAX_QUEUE_FETCH, scope: reviewScope, chapterLabel }),
      getAdaptiveStudyQueue(courseId, MAX_QUEUE_FETCH),
    ]).then(([review, adaptive]) => {
      if (!active) return;
      if (!review.data) {
        setChooserState({ kind: "error", error: describeError(review.status, "Loading review queue") });
        setPhase("chooser");
        return;
      }
      const questionCount = adaptive.data?.activities.filter((item) => item.activity_type === "question").length ?? 0;
      const metrics = queueMetrics(review.data, questionCount, chapterLabel);
      if (metrics.due === 0) {
        setChooserState({
          kind: "ready",
          due: metrics.due,
          new: metrics.new,
          total: metrics.total,
        });
        setPhase("chooser");
        return;
      }
      startSession(metrics.due);
    });
    return () => {
      active = false;
    };
  }, [phase, courseId, chapterLabel, queryKey, reviewScope, startSession]);

  const discardResumedSession = useCallback(() => {
    clearActiveReviewSession();
    setIsResumedSession(false);
    setCards([]);
    setCardIndex(0);
    setGradeCounts({});
    setSessionState({ kind: "loading" });
    setPhase("chooser");
  }, []);

  const reveal = useCallback(() => setRevealed(true), []);

  const requestGrade = useCallback(
    (value: number) => {
      const card = cards[cardIndex];
      if (!card || !revealed || gradePending) return;
      setGradeRequest({ grade: value as ReviewGrade, token: Date.now() });
    },
    [cards, cardIndex, gradePending, revealed],
  );

  const completeSession = useCallback(
    (tally: Record<number, number>, missedIds: string[]) => {
      if (!courseId) return;
      const completed: CompletedReviewSession = {
        version: 1,
        sessionId: activeSessionId ?? newSessionId(),
        courseId,
        scope: reviewScope ?? "available",
        chapterLabel: chapterLabel ?? null,
        endedAt: Date.now(),
        gradedTally: tally,
        againCardIds: missedIds,
      };
      writeCompletedReviewSession(completed);
      setCompletedSession(completed);
      clearActiveReviewSession();
      setSessionState({ kind: "done" });
      router.replace(`/review?course=${courseId}&completed=${completed.sessionId}`);
    },
    [activeSessionId, chapterLabel, courseId, reviewScope, router],
  );

  const goBackToReview = useCallback(() => {
    if (!courseId) {
      setPhase("hub");
      router.replace("/review");
      return;
    }
    setSessionState({ kind: "loading" });
    setChooserState({ kind: "loading" });
    setReplayMissingMessage(null);
    setPhase("chooser");
    router.replace(`/review?course=${courseId}`);
  }, [courseId, router]);

  const startMissedReplay = useCallback(async () => {
    if (!completedSession || completedSession.againCardIds.length === 0) return;
    const replaySource = {
      courseId: completedSession.courseId,
      sessionId: completedSession.sessionId,
      scope: completedSession.scope,
      chapterLabel: completedSession.chapterLabel,
    };
    const requestToken = replayRequestTokenRef.current + 1;
    replayRequestTokenRef.current = requestToken;
    setPhase("session");
    setSessionState({ kind: "loading" });
    setReplayMissingMessage(null);
    const activeUrl = activeReviewUrl(replaySource.courseId, replaySource.scope, replaySource.chapterLabel);
    const activeQuery = activeUrl.split("?")[1] ?? "";
    reconciledQueryRef.current = activeQuery;
    router.replace(activeUrl);
    const { data, status } = await getReviewSelection(completedSession.courseId, completedSession.againCardIds);
    const latest = latestQueryRef.current;
    if (
      replayRequestTokenRef.current !== requestToken ||
      latest.courseParam !== replaySource.courseId ||
      (latest.completedParam !== null && latest.completedParam !== replaySource.sessionId)
    ) {
      return;
    }
    if (!data) {
      setSessionState({ kind: "error", error: describeError(status, "Loading missed cards") });
      return;
    }
    if (data.missing_card_ids.length > 0) {
      const count = data.missing_card_ids.length;
      setReplayMissingMessage(
        `${count} missed ${count === 1 ? "card is" : "cards are"} no longer available.`,
      );
    }
    if (data.cards.length === 0) {
      setSessionState({ kind: "empty" });
      return;
    }
    const sessionId = newSessionId();
    const startedAt = Date.now();
    setCourseId(completedSession.courseId);
    setActiveSessionId(sessionId);
    setCards(data.cards);
    setQuestions([]);
    setCardIndex(0);
    setRevealed(false);
    setGradeRequest(null);
    setGradePending(false);
    setGradeCounts({});
    setAgainCardIds([]);
    setSessionSize(data.cards.length);
    setSessionStartedAt(startedAt);
    setIsResumedSession(false);
    writeActiveReviewSession({
      version: 1,
      sessionId,
      courseId: completedSession.courseId,
      scope: completedSession.scope,
      chapterLabel: completedSession.chapterLabel,
      chosenSize: data.cards.length,
      remainingCardIds: data.cards.map((card) => card.id),
      gradedTally: {},
      againCardIds: [],
      startedAt,
    });
    setSessionState({ kind: "active" });
  }, [completedSession, router]);

  const handleCardGraded = useCallback(
    (value: ReviewGrade) => {
      const card = cards[cardIndex];
      if (!card) return;
      const nextTally = { ...gradeCounts, [value]: (gradeCounts[value] ?? 0) + 1 };
      const nextAgainCardIds = value === 1 ? [...againCardIds, card.id] : againCardIds;
      setGradeCounts(nextTally);
      setAgainCardIds(nextAgainCardIds);
      setGradePending(false);
      setReplayMissingMessage(null);

      const nextIndex = cardIndex + 1;
      if (nextIndex >= cards.length) {
        if (questions.length === 0) {
          completeSession(nextTally, nextAgainCardIds);
        } else {
          if (courseId && sessionSize !== null) {
            writeActiveReviewSession({
              version: 1,
              sessionId: activeSessionId ?? newSessionId(),
              courseId,
              scope: reviewScope ?? "available",
              chapterLabel: chapterLabel ?? null,
              chosenSize: sessionSize,
              remainingCardIds: [],
              gradedTally: nextTally,
              againCardIds: nextAgainCardIds,
              startedAt: sessionStartedAt,
            });
          }
          setCardIndex(nextIndex);
        }
      } else {
        if (courseId && sessionSize !== null) {
          writeActiveReviewSession({
            version: 1,
            sessionId: activeSessionId ?? newSessionId(),
            courseId,
            scope: reviewScope ?? "available",
            chapterLabel: chapterLabel ?? null,
            chosenSize: sessionSize,
            remainingCardIds: cards.slice(nextIndex).map((c) => c.id),
            gradedTally: nextTally,
            againCardIds: nextAgainCardIds,
            startedAt: sessionStartedAt,
          });
        }
        setCardIndex(nextIndex);
        setRevealed(false);
        setGradeRequest(null);
      }
    },
    [
      activeSessionId,
      againCardIds,
      cards,
      cardIndex,
      chapterLabel,
      courseId,
      gradeCounts,
      questions.length,
      reviewScope,
      completeSession,
      sessionSize,
      sessionStartedAt,
    ],
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
      completeSession(gradeCounts, againCardIds);
      return;
    }
    setQuestionIndex(next);
    setSelectedChoice(null);
    setQuestionResult(null);
  }, [againCardIds, completeSession, gradeCounts, questionIndex, questions.length]);

  const openShortcuts = useCallback(() => setShortcutsOpen(true), []);
  const closeShortcuts = useCallback(() => setShortcutsOpen(false), []);

  const shortcutMap: ShortcutMap =
    phase === "session" && sessionState.kind === "active" && cards[cardIndex]
      ? revealed
        ? gradePending
          ? { "?": openShortcuts }
          : {
            "1": () => requestGrade(1),
            "2": () => requestGrade(2),
            "3": () => requestGrade(3),
            "4": () => requestGrade(4),
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
  } else if (phase === "completed") {
    if (!completedSession) {
      mainContent = (
        <div className="flex flex-1 items-center justify-center p-8">
          <EmptyState
            icon="✨"
            title="Review session unavailable"
            body="This completed session is no longer available."
          />
        </div>
      );
    } else {
      mainContent = (
        <div className="mx-auto flex w-full max-w-md flex-col items-center gap-4 p-8 text-center">
          <h2 className="text-lg font-semibold">Session complete</h2>
          <ul className="flex flex-col gap-2">
            {[1, 2, 3, 4].map((value) => (
              <li key={value}>
                <Badge tone={GRADE_TONES[value]}>
                  {GRADE_LABELS[value]}: {completedSession.gradedTally[value] ?? 0}
                </Badge>
              </li>
            ))}
          </ul>
          {completedSession.againCardIds.length > 0 && (
            <Button variant="primary" onClick={() => void startMissedReplay()}>
              Review missed ({completedSession.againCardIds.length})
            </Button>
          )}
          <Button variant="secondary" onClick={goBackToReview}>
            Back to review
          </Button>
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
      <div className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
        {replayMissingMessage && (
          <p role="alert" className="rounded-md border border-accent/40 bg-accent-soft px-4 py-2 text-sm text-accent-800">
            {replayMissingMessage}
          </p>
        )}
        <EmptyState
          icon="✨"
          title="All caught up"
          body="Generate flashcards from a chapter, or keep reading."
        />
      </div>
    );
  } else if (sessionState.kind === "done") {
    const snapshot = completedSession;
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
        {snapshot && snapshot.againCardIds.length > 0 && (
          <Button variant="primary" onClick={() => void startMissedReplay()}>
            Review missed ({snapshot.againCardIds.length})
          </Button>
        )}
        <Button variant="secondary" onClick={goBackToReview}>
          Back to review
        </Button>
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
        {replayMissingMessage && (
          <p role="alert" className="rounded-md border border-accent/40 bg-accent-soft px-4 py-2 text-sm text-accent-800">
            {replayMissingMessage}
          </p>
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
          <ReviewGradeControls
            card={card}
            request={gradeRequest}
            onPendingChange={setGradePending}
            onGraded={handleCardGraded}
          />
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
    clearActiveReviewSession();
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
