"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import { buildAssetFileUrl } from "@/lib/api/client";
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
}

export default function PdfPagesView({ assetId, pageStart, pageEnd }: PdfPagesViewProps) {
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
        <PdfPage key={pageNumber} doc={effectiveState.doc} pageNumber={pageNumber} />
      ))}
    </div>
  );
}

type PageStatus = "pending" | "rendered" | "error";

function PdfPage({ doc, pageNumber }: { doc: PDFDocumentProxy; pageNumber: number }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textLayerRef = useRef<HTMLDivElement>(null);
  const nearViewport = useNearViewport(containerRef);
  const [status, setStatus] = useState<PageStatus>("pending");

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
            tl.render().catch(() => {
              // The selectable text layer is a progressive enhancement
              // over the already-rendered canvas — a failure here (e.g.
              // AbortException from a cancel racing this promise)
              // shouldn't flip the page into its error state.
            });
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
    };
  }, [nearViewport, doc, pageNumber]);

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
          <div ref={textLayerRef} className="textLayer" />
        </div>
      )}
    </div>
  );
}
