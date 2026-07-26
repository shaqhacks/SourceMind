"use client";

import type { HighlightOut, NoteOut } from "@/lib/api/client";
import { useAssetHtmlStatus } from "@/lib/reader/htmlPagesStatus";

import HtmlPagesView from "./HtmlPagesView";
import PdfPagesView, { type NoteClickHandler, type NoteGutterClick } from "./PdfPagesView";

export interface PagesViewProps {
  courseId: string;
  assetId: string;
  pageStart: number;
  pageEnd: number;
  /** The section's `surface:"pdf"` highlights — forwarded to PdfPagesView
   * only (the pdf.js text-layer renderer this task paints onto).
   * HtmlPagesView, the pdf2htmlEX-enhanced renderer, doesn't get a painter
   * yet. */
  highlights?: HighlightOut[];
  /** Forwarded to PdfPagesView's painter gate. */
  enabled?: boolean;
  /** Positional margin notes + gutter interactions — forwarded to
   * PdfPagesView only (HtmlPagesView has no note gutter yet, same as
   * highlights). */
  notes?: NoteOut[];
  onNoteGutterClick?: NoteGutterClick;
  onNoteClick?: NoteClickHandler;
}

/**
 * Resolves the reader's "pages" mode to the best available renderer for
 * this section's asset: the enhanced pdf2htmlEX HTML view once its
 * conversion has finished, pdf.js otherwise. "converting" gets a subtle,
 * non-blocking note alongside the pdf.js fallback so the wait isn't a
 * silent mystery; "failed"/"none" fall back completely silently — an
 * asset that doesn't (or won't ever) have an enhanced view shouldn't nag
 * about it on every visit.
 */
export default function PagesView({
  courseId,
  assetId,
  pageStart,
  pageEnd,
  highlights,
  enabled,
  notes,
  onNoteGutterClick,
  onNoteClick,
}: PagesViewProps) {
  const status = useAssetHtmlStatus(courseId, assetId);

  if (status === "ready") {
    return <HtmlPagesView assetId={assetId} pageStart={pageStart} pageEnd={pageEnd} />;
  }

  return (
    <div className="flex flex-col gap-3">
      {status === "converting" && (
        <p className="text-xs text-muted-foreground">Enhanced view is being prepared…</p>
      )}
      <PdfPagesView
        assetId={assetId}
        pageStart={pageStart}
        pageEnd={pageEnd}
        highlights={highlights}
        enabled={enabled}
        notes={notes}
        onNoteGutterClick={onNoteGutterClick}
        onNoteClick={onNoteClick}
      />
    </div>
  );
}
