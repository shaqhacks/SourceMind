"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import { buildAssetFileUrl, type HighlightOut, type NoteOut } from "@/lib/api/client";
import { usePdfHighlightPainter, type PdfHighlightPage } from "@/lib/annotations/usePdfHighlightPainter";
import { useNearViewport } from "@/lib/hooks/useNearViewport";
import { GlobalWorkerOptions, TextLayer, getDocument, type PDFDocumentProxy } from "pdfjs-dist";

// The reader subtree this mounts into is already ssr:false (see
// CourseReaderClient.tsx) — pdf.js needs a real Worker/canvas, so this
// whole module only ever runs client-side.
//
// Bundler-native worker reference: `new Worker(new URL(specifier,
// import.meta.url))` is the exact pattern pdfjs-dist's own shipped
// bundler-integration helper (node_modules/pdfjs-dist/webpack.mjs) uses,
// and Turbopack documents supporting the same webpack-compatible
// `new Worker()`/`new URL()` handling — verified against the installed
// 6.1.200 package rather than assumed. The `.min.mjs` build is referenced
// here (that helper's own file uses the unminified one) because a
// worker script is loaded by URL at runtime, bypassing Next's own JS
// minifier — the main pdfjs-dist import below does not need this, since
// it's a normal ESM import that goes through Next's regular bundling.
if (typeof window !== "undefined" && typeof Worker !== "undefined" && !GlobalWorkerOptions.workerPort) {
  GlobalWorkerOptions.workerPort = new Worker(
    new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url),
    { type: "module" },
  );
}

// One parsed document per assetId, shared across every PdfPagesView
// instance/remount for the tab's lifetime — switching chapters within the
// same book (the common case) must not re-fetch and re-parse the whole
// file every time.
const documentCache = new Map<string, Promise<PDFDocumentProxy>>();

function loadDocument(assetId: string): Promise<PDFDocumentProxy> {
  let cached = documentCache.get(assetId);
  if (!cached) {
    cached = getDocument({ url: buildAssetFileUrl(assetId) }).promise;
    // A failed load shouldn't be cached forever as a dead rejected
    // promise — a later mount (e.g. after a retry) should try again.
    cached.catch(() => documentCache.delete(assetId));
    documentCache.set(assetId, cached);
  }
  return cached;
}

// ready/error are tagged with the assetId they resolved for, so a stale
// result (assetId changed again before this one settled) can be detected
// and treated as "loading" at render time — see effectiveState below —
// rather than needing a synchronous setState at the top of the effect to
// reset it, which the react-hooks/set-state-in-effect rule flags (it
// cascades an extra render for no benefit; same id-tagged-state idiom as
// useJobEvents.ts).
type DocState =
  | { kind: "loading" }
  | { kind: "error"; assetId: string }
  | { kind: "ready"; assetId: string; doc: PDFDocumentProxy };

export interface PdfPagesViewProps {
  assetId: string;
  /** 1-based, inclusive — direct pdf.js page numbers (SectionOut's
   * page_start/page_end are per-asset already, no offset needed). */
  pageStart: number;
  pageEnd: number;
  /** The section's `surface:"pdf"` highlights (ReadingColumn's
   * `pdfHighlights` slice) — sliced per-page (`h.page === pageNumber`) and
   * handed to the aggregating painter once each page's text layer is
   * ready. Defaults to empty so callers that don't care about highlights
   * (existing tests, HtmlPagesView's sibling fallback usage) don't have to
   * pass anything. */
  highlights?: HighlightOut[];
  /** Gates the painter — same convention as `useHighlightPainter`'s
   * `enabled`: false (the default) means "don't paint, and clear whatever
   * this painter's names currently hold in the registry." */
  enabled?: boolean;
  /** The section's positional margin notes (surface:"pdf"), sliced per-page
   * (`n.page === pageNumber`) and rendered as gutter pins by each PdfPage.
   * Defaults to empty so callers that don't care don't have to pass it. */
  notes?: NoteOut[];
  /** Fired when the note gutter beside a page is clicked — `anchorY` is the
   * clamped 0..1 fraction of the page height at the click point. */
  onNoteGutterClick?: NoteGutterClick;
  /** Fired when an existing note's pin is clicked. */
  onNoteClick?: NoteClickHandler;
}

export type NoteGutterClick = (
  page: number,
  anchorY: number,
  clientX: number,
  clientY: number,
) => void;
export type NoteClickHandler = (note: NoteOut, clientX: number, clientY: number) => void;

export default function PdfPagesView({
  assetId,
  pageStart,
  pageEnd,
  highlights = [],
  enabled = false,
  notes = [],
  onNoteGutterClick,
  onNoteClick,
}: PdfPagesViewProps) {
  const [state, setState] = useState<DocState>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    loadDocument(assetId).then(
      (doc) => {
        if (active) setState({ kind: "ready", assetId, doc });
      },
      () => {
        if (active) setState({ kind: "error", assetId });
      },
    );
    return () => {
      active = false;
    };
  }, [assetId]);

  // assetId can change again before the effect above's promise settles —
  // a settled result tagged with a now-stale assetId renders as "loading"
  // rather than the wrong document/error.
  const effectiveState: DocState =
    state.kind !== "loading" && state.assetId !== assetId ? { kind: "loading" } : state;

  const retry = () => {
    documentCache.delete(assetId);
    setState({ kind: "loading" });
    loadDocument(assetId).then(
      (doc) => setState({ kind: "ready", assetId, doc }),
      () => setState({ kind: "error", assetId }),
    );
  };

  const pageNumbers = useMemo(() => {
    const numbers: number[] = [];
    for (let n = pageStart; n <= pageEnd; n += 1) numbers.push(n);
    return numbers;
  }, [pageStart, pageEnd]);

  // Ready `.textLayer` containers, keyed by page number — populated by each
  // PdfPage's onTextLayerReady/onTextLayerGone callbacks below as its own
  // text layer finishes (or is torn down). This is the "ref collection"
  // PdfPagesView owns per the task design: individual PdfPage instances
  // never touch CSS.highlights themselves, they only report their container
  // up here once it exists in the DOM with real text-layer spans.
  const [readyPages, setReadyPages] = useState<Map<number, HTMLDivElement>>(() => new Map());

  // Both callbacks return the SAME map reference when the reported change
  // is a no-op (e.g. a redundant ready report for an already-ready page) —
  // React bails out of re-rendering when a state updater returns the prior
  // reference by identity, which keeps an unrelated re-render of this view
  // from also re-triggering the aggregating painter below.
  const handleTextLayerReady = useCallback((pageNumber: number, el: HTMLDivElement) => {
    setReadyPages((prev) => {
      if (prev.get(pageNumber) === el) return prev;
      const next = new Map(prev);
      next.set(pageNumber, el);
      return next;
    });
  }, []);

  const handleTextLayerGone = useCallback((pageNumber: number) => {
    setReadyPages((prev) => {
      if (!prev.has(pageNumber)) return prev;
      const next = new Map(prev);
      next.delete(pageNumber);
      return next;
    });
  }, []);

  // Rebuilt only when the ready-container set or the highlight list itself
  // changes — both are stable references across an unrelated re-render
  // (readyPages via the no-op setState guards above, highlights via the
  // caller's own useMemo in ReadingColumn) — never on every render. That
  // matters because usePdfHighlightPainter's effect is keyed on this
  // array's identity: a fresh array every render would re-run the paint
  // (clear + rebuild all four registry names) for no reason.
  const pdfHighlightPages = useMemo<PdfHighlightPage[]>(() => {
    const pages: PdfHighlightPage[] = [];
    for (const [pageNumber, container] of readyPages) {
      pages.push({ container, highlights: highlights.filter((h) => h.page === pageNumber) });
    }
    return pages;
  }, [readyPages, highlights]);

  usePdfHighlightPainter(pdfHighlightPages, enabled);

  if (effectiveState.kind === "loading") {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Loading original pages…
      </p>
    );
  }

  if (effectiveState.kind === "error") {
    return <ErrorBanner message="Could not load the original PDF pages." onRetry={retry} />;
  }

  return (
    <div className="flex flex-col gap-6">
      {pageNumbers.map((pageNumber) => (
        <PdfPage
          key={pageNumber}
          doc={effectiveState.doc}
          pageNumber={pageNumber}
          onTextLayerReady={handleTextLayerReady}
          onTextLayerGone={handleTextLayerGone}
          notes={notes.filter((n) => n.page === pageNumber)}
          onNoteGutterClick={onNoteGutterClick}
          onNoteClick={onNoteClick}
        />
      ))}
    </div>
  );
}

type PageStatus = "pending" | "rendered" | "error";

interface PdfPageProps {
  doc: PDFDocumentProxy;
  pageNumber: number;
  /** Fired once this page's `.textLayer` container has real, selectable
   * spans in it (`tl.render()` resolved) — the earliest point
   * `rangeForSelector` can resolve anything against it. PdfPagesView uses
   * this to add the container to the aggregating painter's ready set. */
  onTextLayerReady?: (pageNumber: number, el: HTMLDivElement) => void;
  /** Fired from the same effect's cleanup (re-run or unmount) — the
   * container is about to be cleared/detached, so PdfPagesView must drop it
   * from the ready set before a stale, now-empty container gets handed to
   * the painter again. */
  onTextLayerGone?: (pageNumber: number) => void;
  /** This page's notes (already sliced to `n.page === pageNumber` by the parent). */
  notes?: NoteOut[];
  onNoteGutterClick?: NoteGutterClick;
  onNoteClick?: NoteClickHandler;
}

function PdfPage({
  doc,
  pageNumber,
  onTextLayerReady,
  onTextLayerGone,
  notes = [],
  onNoteGutterClick,
  onNoteClick,
}: PdfPageProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textLayerRef = useRef<HTMLDivElement>(null);
  const nearViewport = useNearViewport(containerRef);
  const [status, setStatus] = useState<PageStatus>("pending");
  const [textLayerReady, setTextLayerReady] = useState(false);

  useEffect(() => {
    if (!nearViewport) return undefined;
    let cancelled = false;
    let renderTask: { cancel: () => void } | null = null;
    // Captured directly rather than re-read from textLayerRef.current in
    // cleanup: on unmount, React nulls out DOM refs before this (passive)
    // effect's cleanup runs, so reading the ref there would already be
    // null. The captured element itself stays a valid, mutable DOM node
    // even after being detached, so clearing it here still works and
    // still matters — same instance re-renders (nearViewport/doc/pageNumber
    // deps unchanged) reuse the container node across effect runs.
    let textLayer: TextLayer | null = null;
    let textLayerContainer: HTMLDivElement | null = null;

    doc.getPage(pageNumber).then(
      (page) => {
        if (cancelled) return;
        const canvas = canvasRef.current;
        const wrapper = wrapperRef.current;
        if (!canvas || !wrapper) return;

        const containerWidth = containerRef.current?.clientWidth || 0;
        const baseViewport = page.getViewport({ scale: 1 });
        const scale = containerWidth > 0 ? containerWidth / baseViewport.width : 1;
        // This is the CSS-px viewport — matches canvas.style.width/height
        // below, not the DPR-scaled pixel buffer set on canvas.width/height.
        // The text layer is built from this same viewport so its spans
        // align with the canvas's on-screen box, not its backing buffer.
        const viewport = page.getViewport({ scale });
        const dpr = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;

        const cssWidth = Math.floor(viewport.width);
        const cssHeight = Math.floor(viewport.height);
        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = `${cssWidth}px`;
        canvas.style.height = `${cssHeight}px`;
        wrapper.style.width = `${cssWidth}px`;
        wrapper.style.height = `${cssHeight}px`;

        // `canvas` (not the older, now-backwards-compat-only
        // `canvasContext`) is this version's primary render parameter —
        // verified against the installed 6.1.200 types rather than assumed.
        const task = page.render({
          canvas,
          viewport,
          transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : undefined,
        });
        renderTask = task;
        task.promise.then(
          () => {
            if (!cancelled) setStatus("rendered");
          },
          (err: unknown) => {
            const cancelledByUs =
              typeof err === "object" && err !== null && "name" in err
                ? (err as { name?: string }).name === "RenderingCancelledException"
                : false;
            if (!cancelled && !cancelledByUs) setStatus("error");
          },
        );

        // Built in parallel with the canvas render (not chained after
        // task.promise resolves) — same as pdf.js's own reference viewer,
        // and there's no ordering dependency since the two paint
        // different elements from the same already-computed viewport.
        page.getTextContent().then(
          (textContentSource) => {
            if (cancelled) return;
            const textLayerEl = textLayerRef.current;
            if (!textLayerEl) return;
            const tl = new TextLayer({ textContentSource, container: textLayerEl, viewport });
            textLayer = tl;
            textLayerContainer = textLayerEl;
            // pdf.js's `setLayerDimensions` (called inside the `TextLayer`
            // constructor below) and the `.textLayer` CSS (globals.css)
            // both read `--total-scale-factor`, not `--scale-factor` —
            // that's a derived var pdf.js's own stylesheet computes from
            // `--scale-factor` on a `.pdfViewer .page` ancestor this app
            // doesn't have, so it's set directly here instead. Confirmed
            // against the installed pdfjs-dist 6.1.200 sources.
            textLayerEl.style.setProperty("--total-scale-factor", String(viewport.scale));
            tl.render().then(
              () => {
                if (cancelled) return;
                setTextLayerReady(true);
                onTextLayerReady?.(pageNumber, textLayerEl);
              },
              () => {
                // The selectable text layer is a progressive enhancement
                // over the already-rendered canvas — a failure here (e.g.
                // AbortException from a cancel racing this promise)
                // shouldn't flip the page into its error state, and
                // shouldn't report readiness either.
              },
            );
          },
          () => {
            // Same: a failed text-content fetch shouldn't blank/error the
            // canvas that already rendered successfully.
          },
        );
      },
      () => {
        if (!cancelled) setStatus("error");
      },
    );

    return () => {
      cancelled = true;
      renderTask?.cancel();
      textLayer?.cancel();
      textLayerContainer?.replaceChildren();
      // Reset/report unconditionally (not gated on the `cancelled` flag
      // this cleanup itself just set) — this covers both a real unmount
      // (nothing reads `textLayerReady` again anyway) and this same
      // instance's effect re-running for a new nearViewport/doc/pageNumber
      // (where the container is about to be rebuilt from scratch and must
      // not still be sitting in the parent's ready set while empty).
      setTextLayerReady(false);
      onTextLayerGone?.(pageNumber);
    };
  }, [nearViewport, doc, pageNumber, onTextLayerReady, onTextLayerGone]);

  return (
    <div
      ref={containerRef}
      data-testid={`pdf-page-${pageNumber}`}
      className="mx-auto flex min-h-[500px] w-full items-center justify-center"
    >
      {!nearViewport ? (
        <span role="status" className="text-xs text-muted-foreground">
          Page {pageNumber}
        </span>
      ) : status === "error" ? (
        <ErrorBanner message={`Could not render page ${pageNumber}.`} />
      ) : (
        <div ref={wrapperRef} style={{ position: "relative" }}>
          <canvas ref={canvasRef} aria-label={`Page ${pageNumber}`} className="block shadow-sm" />
          <div
            ref={textLayerRef}
            className="textLayer"
            data-pdf-page={pageNumber}
            data-text-layer-ready={textLayerReady}
          />
          {/* Margin-note gutter — anchored to this position:relative wrapper so
              a pin's `top: {anchor_y*100}%` tracks the page height at any
              width (no JS geometry). The click strip sits in the right gutter;
              a click computes anchor_y from the live rect. Keyboard fallback
              (Enter/Space) drops a note at the page middle, since placing at a
              precise y is inherently pointer-driven. */}
          <div
            data-testid={`note-gutter-${pageNumber}`}
            role="button"
            tabIndex={0}
            aria-label={`Add a note beside page ${pageNumber}`}
            className="absolute inset-y-0 left-full ml-2 w-6 cursor-copy rounded bg-muted-foreground/5 hover:bg-muted-foreground/10"
            onClick={(event) => {
              event.stopPropagation();
              const rect = event.currentTarget.getBoundingClientRect();
              // Bail if the page hasn't laid out yet (0-height rect during the
              // pending window before doc.getPage resolves) — else anchor_y is
              // NaN and the create is rejected 422 with only a generic banner.
              if (rect.height <= 0) return;
              const anchorY = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
              onNoteGutterClick?.(pageNumber, anchorY, event.clientX, event.clientY);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                const rect = event.currentTarget.getBoundingClientRect();
                onNoteGutterClick?.(pageNumber, 0.5, rect.left, rect.top + rect.height / 2);
              }
            }}
          />
          {(() => {
            // Simple collision nudge (spec MVP, not a full solver): pins are
            // ordered by anchor_y and any within a small y-fraction of the
            // previous one get a stacked downward pixel offset, so two
            // near-coincident notes don't render as one indistinguishable pin.
            // The -50% keeps the pin centered on its anchor; the offset stacks
            // from there.
            const ordered = [...notes].sort((a, b) => a.anchor_y - b.anchor_y);
            let prevAnchorY = -Infinity;
            let stack = 0;
            return ordered.map((note) => {
              stack = note.anchor_y - prevAnchorY <= 0.02 ? stack + 1 : 0;
              prevAnchorY = note.anchor_y;
              const offsetPx = stack * 16;
              return (
                <button
                  key={note.id}
                  type="button"
                  data-testid={`note-pin-${note.id}`}
                  style={{
                    top: `${note.anchor_y * 100}%`,
                    transform: `translateY(calc(-50% + ${offsetPx}px))`,
                  }}
                  aria-label={`Note on page ${pageNumber}`}
                  className="absolute left-full ml-2 flex h-5 w-6 items-center justify-center rounded bg-accent text-[10px] text-white shadow hover:opacity-90"
                  onClick={(event) => {
                    event.stopPropagation();
                    onNoteClick?.(note, event.clientX, event.clientY);
                  }}
                >
                  ●
                </button>
              );
            });
          })()}
        </div>
      )}
    </div>
  );
}
