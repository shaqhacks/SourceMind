"use client";

import type { RefObject } from "react";
import Link from "next/link";

import ErrorBanner from "@/components/ErrorBanner";
import Markdown from "@/components/Markdown";
import { prefsToCssVars, type TypographyPrefs } from "@/lib/hooks/useTypographyPrefs";
import type { ReaderSection, SectionBodyState, ViewMode } from "@/lib/reader/types";

import CardsCTA from "./CardsCTA";
import LessonPane, { type LessonDisplayStatus } from "./LessonPane";
import PagesView from "./PagesView";
import SectionCards from "./SectionCards";

export interface ReadingColumnProps {
  courseId: string;
  section: ReaderSection;
  mode: ViewMode;
  typography: TypographyPrefs;
  headingRef: RefObject<HTMLHeadingElement | null>;
  columnRef: RefObject<HTMLDivElement | null>;
  body: SectionBodyState;
  onLessonStatusChange: (sectionId: string, status: LessonDisplayStatus) => void;
  onNext: () => void;
  onPrevious: () => void;
  /** The next/previous content section's title, or null when there isn't
   * one — the matching chevron isn't rendered at all in that case (the
   * mdBook-style edge behavior: no dead click zone at the first/last
   * chapter, matching the existing clamp-instead-of-wrap keyboard nav). */
  nextTitle: string | null;
  previousTitle: string | null;
}

function pageRange(section: ReaderSection): string | null {
  if (section.page_start === null || section.page_end === null) return null;
  return `p.${section.page_start}–${section.page_end}`;
}

const NON_CONTENT_BANNER_TEXT: Record<"practice" | "answers", string> = {
  practice: "This is practice material, not regular reading — it belongs on the chapter test page.",
  answers: "This is an answer key, not regular reading — it belongs on the chapter test page.",
};

const CHEVRON_ZONE_CLASSES =
  "group absolute inset-y-0 z-10 flex w-12 items-center justify-center text-muted-foreground/40 transition-colors hover:bg-muted-foreground/5 hover:text-foreground focus-visible:bg-muted-foreground/5 focus-visible:text-foreground";

export default function ReadingColumn({
  courseId,
  section,
  mode,
  typography,
  headingRef,
  columnRef,
  body,
  onLessonStatusChange,
  onNext,
  onPrevious,
  nextTitle,
  previousTitle,
}: ReadingColumnProps) {
  const pages = pageRange(section);

  return (
    <div className="relative flex min-h-0 flex-1">
      {previousTitle !== null && (
        <button
          type="button"
          onClick={onPrevious}
          aria-label={`Previous chapter: ${previousTitle}`}
          className={`${CHEVRON_ZONE_CLASSES} left-0`}
        >
          <span aria-hidden="true" className="text-2xl">
            ‹
          </span>
        </button>
      )}
      <div
        ref={columnRef}
        data-testid="reading-column"
        className="reading-column min-h-0 flex-1 overflow-y-auto"
        style={prefsToCssVars(typography)}
      >
        <article className="reading-measure mx-auto px-6 py-10 font-serif">
          {/* Reached only via an explicit deep link (Sidebar/keyboard nav
              never select these, see chapterGroups.ts and CourseReader's
              goToOffset) — surfaced so it isn't a silent, unexplained
              dead end rather than blocked outright. */}
          {section.kind !== "content" && (
            <div
              role="note"
              aria-label="Reading flow notice"
              className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-accent/30 bg-accent/5 px-4 py-3 text-sm"
            >
              <span>{NON_CONTENT_BANNER_TEXT[section.kind]}</span>
              {section.chapter_label !== null && (
                <Link
                  href={`/course/${courseId}/chapter/${encodeURIComponent(section.chapter_label)}/test`}
                  className="shrink-0 font-medium text-accent underline"
                >
                  Go to chapter test
                </Link>
              )}
            </div>
          )}
          {pages ? <p className="mb-2 font-sans text-sm text-muted-foreground">{pages}</p> : null}
          {/* Explicit heading (not part of the markdown body) so chapter-change
              focus management has a stable, deterministic target regardless of
              what heading levels the section's own source text happens to use. */}
          <h2
            ref={headingRef}
            tabIndex={-1}
            className="mb-6 font-sans text-2xl font-semibold outline-none"
          >
            {section.title}
          </h2>
          {mode === "source" ? (
            body.kind === "loading" ? (
              <p role="status" className="text-sm text-muted-foreground">
                Loading chapter…
              </p>
            ) : body.kind === "error" ? (
              <ErrorBanner message={body.message} />
            ) : (
              <Markdown>{body.body}</Markdown>
            )
          ) : mode === "pages" ? (
            section.asset_id && section.page_start !== null && section.page_end !== null ? (
              // Keyed on section id: switching chapters is a fresh document
              // view, not a state transition (PdfPagesView/HtmlPagesView's
              // own per-assetId caches mean this remount is cheap when the
              // new section shares the same book).
              <PagesView
                key={section.id}
                courseId={courseId}
                assetId={section.asset_id}
                pageStart={section.page_start}
                pageEnd={section.page_end}
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                Original pages aren&apos;t available for this section.
              </p>
            )
          ) : (
            // Keyed on section id: switching chapters while in lesson view is
            // a fresh pane, not a state transition — remounting gives it
            // clean initial state for free instead of a reset-in-effect.
            <LessonPane
              key={section.id}
              sectionId={section.id}
              onStatusChange={(status) => onLessonStatusChange(section.id, status)}
            />
          )}
          <div className="mt-8 border-t border-border pt-4">
            <CardsCTA key={`cta-${section.id}`} sectionId={section.id} />
            <SectionCards key={`cards-${section.id}`} sectionId={section.id} />
          </div>
        </article>
      </div>
      {nextTitle !== null && (
        <button
          type="button"
          onClick={onNext}
          aria-label={`Next chapter: ${nextTitle}`}
          className={`${CHEVRON_ZONE_CLASSES} right-0`}
        >
          <span aria-hidden="true" className="text-2xl">
            ›
          </span>
        </button>
      )}
    </div>
  );
}
