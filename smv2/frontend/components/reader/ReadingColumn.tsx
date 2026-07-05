"use client";

import type { RefObject } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Markdown from "@/components/Markdown";
import { prefsToCssVars, type TypographyPrefs } from "@/lib/hooks/useTypographyPrefs";
import type { ReaderSection, SectionBodyState } from "@/lib/reader/types";

export type ViewMode = "source" | "lesson";

export interface ReadingColumnProps {
  section: ReaderSection;
  mode: ViewMode;
  typography: TypographyPrefs;
  headingRef: RefObject<HTMLHeadingElement | null>;
  columnRef: RefObject<HTMLDivElement | null>;
  body: SectionBodyState;
}

function pageRange(section: ReaderSection): string | null {
  if (section.page_start === null || section.page_end === null) return null;
  return `p.${section.page_start}–${section.page_end}`;
}

export default function ReadingColumn({
  section,
  mode,
  typography,
  headingRef,
  columnRef,
  body,
}: ReadingColumnProps) {
  const pages = pageRange(section);

  return (
    <div
      ref={columnRef}
      data-testid="reading-column"
      className="reading-column min-h-0 flex-1 overflow-y-auto"
      style={prefsToCssVars(typography)}
    >
      <article className="reading-measure mx-auto px-6 py-10 font-serif">
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
        ) : (
          <div
            role="status"
            className="rounded-md border border-dashed border-border p-6 text-sm text-muted-foreground"
          >
            No lesson yet — generation arrives in Phase 3.
          </div>
        )}
      </article>
    </div>
  );
}
