"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import CardsTable from "@/components/flashcards/CardsTable";
import ChapterDeckCard from "@/components/flashcards/ChapterDeckCard";
import ErrorBanner from "@/components/ErrorBanner";
import EmptyState from "@/components/ui/EmptyState";
import Skeleton from "@/components/ui/Skeleton";
import { describeError, type FetchError } from "@/lib/api/errors";
import {
  getReviewQueue,
  listCards,
  listChapters,
  listCourses,
  MAX_QUEUE_FETCH,
  type CardOut,
  type ChapterOut,
  type CourseOut,
  type ReviewQueueCardOut,
} from "@/lib/api/client";
import { subscribeCardsSettled } from "@/lib/cards/cardsBus";
import { useRouteFocus } from "@/lib/hooks/useRouteFocus";

type CoursesState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "ready"; courses: CourseOut[] };

type CourseDataState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | {
      kind: "ready";
      chapters: ChapterOut[];
      cardsBySection: Record<string, CardOut[]>;
      dueCards: ReviewQueueCardOut[];
      totalCards: number;
    };

/** Cards live on a chapter's own content sections (ChapterOut.section_ids)
 * — practice/answers sections are excluded, mirroring generateTest's own
 * chapter-scoped exclusion of that material. */
function cardsForChapter(
  chapter: ChapterOut,
  cardsBySection: Record<string, CardOut[]>,
): CardOut[] {
  return chapter.section_ids.flatMap((id) => cardsBySection[id] ?? []);
}

/** "Due" here matches CourseReviewSummaryOut.overdue_count's own definition
 * (ReviewState.due_at <= now) — new/never-reviewed cards are excluded, same
 * as how the review hub already reports "X due · Y new" as two separate
 * numbers rather than one combined count. */
function dueCountForChapter(
  cards: CardOut[],
  dueById: Map<string, ReviewQueueCardOut>,
): number {
  return cards.filter((card) => dueById.get(card.id)?.is_due === true).length;
}

async function loadCourseData(courseId: string): Promise<CourseDataState> {
  const [chaptersResult, queueResult] = await Promise.all([
    listChapters(courseId),
    getReviewQueue(courseId, { scope: "all", limit: MAX_QUEUE_FETCH }),
  ]);
  if (!chaptersResult.data) {
    return { kind: "error", error: describeError(chaptersResult.status, "Loading chapters") };
  }
  if (!queueResult.data) {
    return { kind: "error", error: describeError(queueResult.status, "Loading review queue") };
  }

  // Front matter (null chapter_label) has nothing to study/link, same
  // exclusion StudyNextList/QuizzesToTakePanel already apply.
  const chapters = chaptersResult.data.filter((chapter) => chapter.chapter_label !== null);
  const sectionIds = Array.from(new Set(chapters.flatMap((chapter) => chapter.section_ids)));
  const cardsResults = await Promise.all(sectionIds.map((id) => listCards(id)));
  const failed = cardsResults.find((result) => !result.data);
  if (failed) {
    return { kind: "error", error: describeError(failed.status, "Loading flashcards") };
  }

  const cardsBySection: Record<string, CardOut[]> = {};
  sectionIds.forEach((id, index) => {
    cardsBySection[id] = cardsResults[index].data ?? [];
  });

  return {
    kind: "ready",
    chapters,
    cardsBySection,
    dueCards: queueResult.data.cards,
    totalCards: queueResult.data.total_count,
  };
}

/** courseData tagged with the course it belongs to — the same "derive
 * staleness during render instead of resetting via an effect" idiom
 * useJobEvents.ts uses for its jobId-tagged state, rather than an effect
 * synchronously setState-ing back to "loading" on every course switch
 * (which react-hooks/set-state-in-effect flags as a cascading-render
 * anti-pattern; app/review/page.tsx's own course-scoped fetch effect
 * follows the same non-resetting shape for the same reason). */
interface CourseDataEntry {
  courseId: string;
  state: CourseDataState;
}

export default function FlashcardsClient() {
  const [coursesState, setCoursesState] = useState<CoursesState>({ kind: "loading" });
  const [selectedCourseId, setSelectedCourseId] = useState<string | null>(null);
  const [courseDataEntry, setCourseDataEntry] = useState<CourseDataEntry | null>(null);
  const [browsedChapterLabel, setBrowsedChapterLabel] = useState<string | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  useRouteFocus(headingRef);

  // Mirrors selectedCourseId for reloadCourseData's resolve-time check
  // above — a ref, not the state variable itself, because reloadCourseData
  // (and the .then() closure it creates) is called from a specific render
  // and would otherwise only ever see that render's own selectedCourseId
  // (which always equals the courseId argument, defeating the check).
  const selectedCourseIdRef = useRef<string | null>(selectedCourseId);
  useEffect(() => {
    selectedCourseIdRef.current = selectedCourseId;
  }, [selectedCourseId]);

  function fetchCourses() {
    listCourses().then(({ data, status }) => {
      if (data) {
        const ready = data.filter((course) => course.status === "ready");
        setCoursesState({ kind: "ready", courses: ready });
        setSelectedCourseId((current) => current ?? ready[0]?.id ?? null);
      } else {
        setCoursesState({ kind: "error", error: describeError(status, "Loading courses") });
      }
    });
  }

  // Mount-only: no synchronous setState here (the initial useState above
  // already covers "loading") — only the retry handler below resets state
  // synchronously, and it does so from a click handler, not an effect.
  useEffect(() => {
    fetchCourses();
  }, []);

  // Shared by the course-change effect, the settle-bus subscription, and
  // the error banner's retry button. Every setState here happens inside
  // the fetch's own .then() — never synchronously in an effect body.
  //
  // "Whichever response resolves last wins" is NOT enough on its own: if a
  // slow fetch for an abandoned course resolves after a newer course's
  // fetch already landed, writing it would overwrite the newer course's
  // good entry with a mismatched-courseId one — the render-time comparison
  // below then reads that as "loading" (correctly hiding the stale data),
  // but the newer course's already-fetched data is gone, and nothing
  // re-fetches it (the effect only re-runs when selectedCourseId itself
  // changes again) — a permanent skeleton. So the write itself is guarded:
  // compare this fetch's target courseId against the selection at RESOLVE
  // time (via a ref — `selectedCourseId` closed over by this function's own
  // call would just equal `courseId` and never catch a switch that happened
  // after the call), and skip the write entirely for a since-abandoned
  // course rather than let it replace a newer entry.
  function reloadCourseData(courseId: string) {
    loadCourseData(courseId).then((result) => {
      setCourseDataEntry((current) =>
        courseId === selectedCourseIdRef.current ? { courseId, state: result } : current,
      );
      if (result.kind === "ready" && courseId === selectedCourseIdRef.current) {
        setBrowsedChapterLabel((current) => {
          if (current && result.chapters.some((c) => c.chapter_label === current)) return current;
          const firstWithCards = result.chapters.find(
            (chapter) => cardsForChapter(chapter, result.cardsBySection).length > 0,
          );
          return firstWithCards?.chapter_label ?? null;
        });
      }
    });
  }

  useEffect(() => {
    if (selectedCourseId) reloadCourseData(selectedCourseId);
  }, [selectedCourseId]);

  // A generation job settling anywhere (this page's own "Generate cards"
  // buttons, or the reader) invalidates the currently loaded card/due data
  // for whichever course is selected — refetch it rather than going stale.
  // This setState reaches React from inside an external pub/sub callback
  // (fired later, in response to an outside event), the exact "subscribe
  // for updates from an external system" shape the lint rule wants —
  // unlike the two calls above, this one isn't flagged.
  useEffect(() => {
    return subscribeCardsSettled(() => {
      if (selectedCourseId) reloadCourseData(selectedCourseId);
    });
  }, [selectedCourseId]);

  if (coursesState.kind === "loading") {
    return (
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-8 py-10">
        <Skeleton className="h-9 w-56" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (coursesState.kind === "error") {
    return (
      <div className="mx-auto w-full max-w-6xl px-8 py-10">
        <ErrorBanner
          status={coursesState.error.status}
          message={coursesState.error.message}
          onRetry={() => {
            setCoursesState({ kind: "loading" });
            fetchCourses();
          }}
        />
      </div>
    );
  }

  const { courses } = coursesState;

  if (courses.length === 0) {
    return (
      <div className="mx-auto w-full max-w-6xl px-8 py-10">
        <h1 ref={headingRef} tabIndex={-1} className="font-heading text-[34px] outline-none">
          Flashcards
        </h1>
        <div className="mt-6">
          <EmptyState
            icon="🗂️"
            title="No courses yet"
            body="Upload a PDF from Home to start a course, then generate flashcards from its chapters."
            cta={
              <Link href="/" className="text-sm font-medium text-accent underline">
                Go to Home
              </Link>
            }
          />
        </div>
      </div>
    );
  }

  const selectedCourse = courses.find((c) => c.id === selectedCourseId) ?? courses[0];
  // Derived, not stored: a stale entry (still tagged with a since-abandoned
  // courseId) reads as "loading" here rather than needing an effect to
  // reset it first — see the CourseDataEntry comment above.
  const courseData: CourseDataState =
    courseDataEntry && courseDataEntry.courseId === selectedCourse.id
      ? courseDataEntry.state
      : { kind: "loading" };
  const dueById =
    courseData.kind === "ready"
      ? new Map(courseData.dueCards.map((card) => [card.id, card]))
      : new Map<string, ReviewQueueCardOut>();
  const cardMetadata = courseData.kind === "ready" ? courseData.dueCards : null;
  const totalCards = courseData.kind === "ready" ? courseData.totalCards : null;
  const dueCards = cardMetadata ? cardMetadata.filter((card) => card.is_due).length : null;
  const newCards = cardMetadata ? cardMetadata.filter((card) => card.is_new).length : null;
  const needsAttentionCards = cardMetadata
    ? cardMetadata.filter((card) => card.last_grade === 1).length
    : null;

  const browsedChapter =
    courseData.kind === "ready"
      ? courseData.chapters.find((c) => c.chapter_label === browsedChapterLabel)
      : undefined;
  const browsedCards =
    browsedChapter && courseData.kind === "ready"
      ? cardsForChapter(browsedChapter, courseData.cardsBySection)
      : [];

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-8 py-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 ref={headingRef} tabIndex={-1} className="font-heading text-[34px] outline-none">
            Flashcards
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {totalCards === null || dueCards === null || newCards === null || needsAttentionCards === null
              ? "Loading…"
              : `${totalCards} total · ${dueCards} due · ${newCards} new · ${needsAttentionCards} needs attention`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href={`/review?course=${encodeURIComponent(selectedCourse.id)}&scope=available&start=due`}
            className="rounded-md bg-accent-700 px-4 py-2 font-heading text-sm text-background transition-colors hover:bg-accent-800 active:bg-accent-900"
          >
            Review due{dueCards !== null ? ` (${dueCards})` : ""}
          </Link>
          <Link
            href={`/review?course=${encodeURIComponent(selectedCourse.id)}&scope=all`}
            className="rounded-md border border-border bg-surface-raised px-4 py-2 font-heading text-sm transition-colors hover:bg-foreground/[0.07] active:bg-foreground/[0.14]"
          >
            Review all{totalCards !== null ? ` (${totalCards})` : ""}
          </Link>
          <Link
            href={`/review?course=${encodeURIComponent(selectedCourse.id)}&scope=needs_attention`}
            className="rounded-md border border-border bg-surface-raised px-4 py-2 font-heading text-sm transition-colors hover:bg-foreground/[0.07] active:bg-foreground/[0.14]"
          >
            Needs attention{needsAttentionCards !== null ? ` (${needsAttentionCards})` : ""}
          </Link>
        </div>
      </div>

      {courses.length > 1 && (
        <div
          role="tablist"
          aria-label="Course"
          className="flex w-fit gap-1 rounded-md border border-border bg-surface-raised p-1"
        >
          {courses.map((course) => (
            <button
              key={course.id}
              type="button"
              role="tab"
              aria-selected={course.id === selectedCourse.id}
              onClick={() => setSelectedCourseId(course.id)}
              className={`rounded-[6px] px-3 py-1.5 text-sm font-medium transition-colors ${
                course.id === selectedCourse.id
                  ? "bg-background text-accent-700 shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {course.title}
            </button>
          ))}
        </div>
      )}

      {courseData.kind === "loading" ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : courseData.kind === "error" ? (
        <ErrorBanner
          status={courseData.error.status}
          message={courseData.error.message}
          onRetry={() => reloadCourseData(selectedCourse.id)}
        />
      ) : courseData.chapters.length === 0 ? (
        <EmptyState
          icon="🗂️"
          title="No chapters yet"
          body="This course hasn't finished ingesting, or has no chapters to generate cards from."
        />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {courseData.chapters.map((chapter, index) => {
              const cards = cardsForChapter(chapter, courseData.cardsBySection);
              return (
                <ChapterDeckCard
                  key={chapter.chapter_label}
                  courseId={selectedCourse.id}
                  chapterNumber={index + 1}
                  title={chapter.chapter_label ?? ""}
                  sectionIds={chapter.section_ids}
                  cards={cards}
                  dueCount={dueCountForChapter(cards, dueById)}
                  isBrowsed={chapter.chapter_label === browsedChapterLabel}
                  onBrowse={() => setBrowsedChapterLabel(chapter.chapter_label)}
                />
              );
            })}
          </div>

          {browsedChapter && browsedCards.length > 0 && (
            <CardsTable
              chapterTitle={browsedChapter.chapter_label ?? ""}
              cards={browsedCards}
              dueCardsById={dueById}
            />
          )}
        </>
      )}
    </div>
  );
}
