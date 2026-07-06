"use client";

import { useAssetHtmlStatus } from "@/lib/reader/htmlPagesStatus";

import HtmlPagesView from "./HtmlPagesView";
import PdfPagesView from "./PdfPagesView";

export interface PagesViewProps {
  courseId: string;
  assetId: string;
  pageStart: number;
  pageEnd: number;
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
export default function PagesView({ courseId, assetId, pageStart, pageEnd }: PagesViewProps) {
  const status = useAssetHtmlStatus(courseId, assetId);

  if (status === "ready") {
    return <HtmlPagesView assetId={assetId} pageStart={pageStart} pageEnd={pageEnd} />;
  }

  return (
    <div className="flex flex-col gap-3">
      {status === "converting" && (
        <p className="text-xs text-muted-foreground">Enhanced view is being prepared…</p>
      )}
      <PdfPagesView assetId={assetId} pageStart={pageStart} pageEnd={pageEnd} />
    </div>
  );
}
