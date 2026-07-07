"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import ErrorBanner from "@/components/ErrorBanner";
import HintRow from "@/components/HintRow";
import Markdown from "@/components/Markdown";
import ShortcutsOverlay, { type ShortcutHint } from "@/components/ShortcutsOverlay";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  getReviewQueue,
  getReviewSummary,
  gradeCard,
  type ReviewQueueCardOut,
  type ReviewSummaryOut,
} from "@/lib/api/client";
import { useKeyboardShortcuts, type ShortcutMap } from "@/lib/hooks/useKeyboardShortcuts";
import { useRouteFocus } from "@/lib/hooks/useRouteFocus";
import { notifyReviewSettled } from "@/lib/review/reviewBus";

const SHORTCUT_HINTS: ShortcutHint[] = [
  { keys: "space", description: "Reveal answer" },
  { keys: "1 2 3 4", description: "Grade: Again / Hard / Good / Easy" },
  { keys: "?", description: "Show this help" },
];

const GRADE_LABELS: Record<number, string> = { 1: "Again", 2: "Hard", 3: "Good", 4: "Easy" };
// review_queue's `limit` caps at 200 — a session's "all" is "all up to
// that cap", not literally unbounded. Fine at this app's scale.
const MAX_QUEUE_FETCH = 200;

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
  const [hubState, setHubState] = useState<HubState>({ kind: "loading" });
  const [chooserState, setChooserState] = useState<ChooserState>({ kind: "loading" });
  const [sessionState, setSessionState] = useState<SessionState>({ kind: "loading" });
  const [sessionSize, setSessionSize] = useState<number | null>(null);
  const [sessionStartedAt, setSessionStartedAt] = useState(0);
  const [isResumedSession, setIsResumedSession] = useState(false);
  const [cards, setCards] = useState<ReviewQueueCardOut[]>([]);
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
    getReviewQueue(id, MAX_QUEUE_FETCH).then(({ data, status }) => {
      if (data) {
        setChooserState({ kind: "ready", due: data.due, new: data.new, total: data.total });
      } else {
        setChooserState({ kind: "error", error: describeError(status, "Loading review queue") });
      }
    });
  }, []);

  useEffect(() => {
    if (phase !== "chooser" || !courseId) return;
    let active = true;
    getReviewQueue(courseId, MAX_QUEUE_FETCH).then(({ data, status }) => {
      if (!active) return;
      if (data) {
        setChooserState({ kind: "ready", due: data.due, new: data.new, total: data.total });
      } else {
        setChooserState({ kind: "error", error: describeError(status, "Loading review queue") });
      }
    });
    return () => {
      active = false;
    };
  }, [phase, courseId]);

  function goToChooser(id: string) {
    setCourseId(id);
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
      getReviewQueue(courseId, size).then(({ data, status }) => {
        if (!data) {
          setSessionState({ kind: "error", error: describeError(status, "Loading review queue") });
          return;
        }
        if (data.cards.length === 0) {
          setSessionState({ kind: "empty" });
          return;
        }
        const startedAt = Date.now();
        setCards(data.cards);
        setCardIndex(0);
        setRevealed(false);
        setCardShownAt(startedAt);
        setSessionStartedAt(startedAt);
        writeStoredSession({
          courseId,
          chosenSize: size,
          remainingCardIds: data.cards.map((card) => card.id),
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
        setSessionState({ kind: "done" });
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
    [cards, cardIndex, cardShownAt, courseId, sessionSize, sessionStartedAt, gradeCounts],
  );

  const openShortcuts = useCallback(() => setShortcutsOpen(true), []);
  const closeShortcuts = useCallback(() => setShortcutsOpen(false), []);

  const shortcutMap: ShortcutMap =
    phase === "session" && sessionState.kind === "active"
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
        <p role="status" className="p-8 text-sm text-muted-foreground">
          Loading review summary…
        </p>
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
    } else if (hubState.summary.due_total === 0) {
      mainContent = (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center text-sm text-muted-foreground">
          <p className="text-lg font-medium text-foreground">No cards due</p>
          <p>Generate flashcards from a chapter, or keep reading.</p>
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
              className="rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100"
            >
              {summary.due_total} due — more than 2 days at your pace.
            </div>
          )}
          <ul className="flex flex-col gap-2">
            {summary.courses.map((course) => (
              <li key={course.course_id}>
                <button
                  type="button"
                  onClick={() => goToChooser(course.course_id)}
                  className="flex w-full items-center justify-between rounded-md border border-border px-4 py-3 text-left text-sm hover:bg-muted-foreground/5"
                >
                  <span className="font-medium">{course.title}</span>
                  <span className="text-muted-foreground">
                    {course.due_count} due · {course.new_count} new
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      );
    }
  } else if (phase === "chooser") {
    if (chooserState.kind === "loading") {
      mainContent = (
        <p role="status" className="p-8 text-sm text-muted-foreground">
          Loading review queue…
        </p>
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
        <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center text-sm text-muted-foreground">
          <p className="text-lg font-medium text-foreground">No cards due</p>
          <p>Generate flashcards from a chapter, or keep reading.</p>
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
              <button
                key={option.value}
                type="button"
                onClick={() => startSession(option.value)}
                className="rounded-md bg-black px-4 py-2 text-sm font-medium text-white dark:bg-white dark:text-black"
              >
                Review {option.label}
              </button>
            ))}
          </div>
        </div>
      );
    }
  } else if (sessionState.kind === "loading") {
    mainContent = (
      <p role="status" className="p-8 text-sm text-muted-foreground">
        Loading cards…
      </p>
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
      <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8 text-center text-sm text-muted-foreground">
        <p className="text-lg font-medium text-foreground">No cards due</p>
        <p>Generate flashcards from a chapter, or keep reading.</p>
      </div>
    );
  } else if (sessionState.kind === "done") {
    mainContent = (
      <div className="mx-auto flex w-full max-w-md flex-col items-center gap-4 p-8 text-center">
        <h2 className="text-lg font-semibold">Session complete</h2>
        <ul className="flex flex-col gap-1 text-sm text-muted-foreground">
          {[1, 2, 3, 4].map((value) => (
            <li key={value}>
              {GRADE_LABELS[value]}: {gradeCounts[value] ?? 0}
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
    mainContent = (
      <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 p-8">
        {isResumedSession && (
          <div
            role="status"
            className="flex items-center justify-between gap-3 rounded-md border border-border bg-accent/5 px-4 py-2 text-sm"
          >
            <span>
              Resumed session — {cards.length - cardIndex} left
            </span>
            <button
              type="button"
              onClick={discardResumedSession}
              className="shrink-0 rounded-md border border-border px-2 py-1 text-xs font-medium"
            >
              Discard
            </button>
          </div>
        )}
        <p role="status" className="text-sm text-muted-foreground">
          {cardIndex + 1} of {cards.length}
        </p>
        <div className="rounded-lg border border-border p-6">
          <Markdown>{card.front_md}</Markdown>
          {revealed && (
            <div className="mt-6 border-t border-border pt-6">
              <Markdown>{card.back_md}</Markdown>
            </div>
          )}
        </div>

        {!revealed ? (
          <button
            type="button"
            onClick={reveal}
            className="self-center rounded-md bg-black px-6 py-2 text-sm font-medium text-white dark:bg-white dark:text-black"
          >
            Reveal (space)
          </button>
        ) : (
          <div className="flex justify-center gap-3">
            {[1, 2, 3, 4].map((value) => (
              <button
                key={value}
                type="button"
                onClick={() => grade(value)}
                className="rounded-md border border-border px-4 py-2 text-sm font-medium"
              >
                {GRADE_LABELS[value]} ({value})
              </button>
            ))}
          </div>
        )}

        <HintRow
          hints={SHORTCUT_HINTS.map((hint) => ({ keys: hint.keys, label: hint.description }))}
        />
      </div>
    );
  }

  return (
    <>
      <div className="border-b border-border px-8 py-4">
        <h1 ref={headingRef} tabIndex={-1} className="text-lg font-semibold outline-none">
          Review
        </h1>
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
