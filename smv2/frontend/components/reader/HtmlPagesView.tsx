"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import {
  buildAssetHtmlPageUrl,
  getAssetHtmlManifest,
  type AssetHtmlManifest,
} from "@/lib/api/client";
import { useNearViewport } from "@/lib/hooks/useNearViewport";

// One fetched manifest per assetId, shared across every HtmlPagesView
// instance/remount for the tab's lifetime — same rationale as
// PdfPagesView's documentCache: switching chapters within the same book
// must not re-fetch every time.
const manifestCache = new Map<string, Promise<AssetHtmlManifest>>();

function loadManifest(assetId: string): Promise<AssetHtmlManifest> {
  let cached = manifestCache.get(assetId);
  if (!cached) {
    cached = getAssetHtmlManifest(assetId).then(({ data }) => {
      if (!data) throw new Error(`no manifest available for asset ${assetId}`);
      return data;
    });
    // A failed load shouldn't be cached forever as a dead rejected
    // promise — a later mount (e.g. after a retry) should try again.
    cached.catch(() => manifestCache.delete(assetId));
    manifestCache.set(assetId, cached);
  }
  return cached;
}

// ready/error are tagged with the assetId they resolved for, same
// id-tagged-state idiom as PdfPagesView's DocState — lets a stale result
// (assetId changed again before this one settled) be detected and shown
// as "loading" at render time instead of needing a synchronous setState
// reset in the effect, which react-hooks/set-state-in-effect flags.
type ManifestState =
  | { kind: "loading" }
  | { kind: "error"; assetId: string }
  | { kind: "ready"; assetId: string; manifest: AssetHtmlManifest };

export interface HtmlPagesViewProps {
  assetId: string;
  /** 1-based, inclusive — same page-numbering convention as PdfPagesView. */
  pageStart: number;
  pageEnd: number;
}

export default function HtmlPagesView({ assetId, pageStart, pageEnd }: HtmlPagesViewProps) {
  const [state, setState] = useState<ManifestState>({ kind: "loading" });

  useEffect(() => {
    let active = true;
    loadManifest(assetId).then(
      (manifest) => {
        if (active) setState({ kind: "ready", assetId, manifest });
      },
      () => {
        if (active) setState({ kind: "error", assetId });
      },
    );
    return () => {
      active = false;
    };
  }, [assetId]);

  const effectiveState: ManifestState =
    state.kind !== "loading" && state.assetId !== assetId ? { kind: "loading" } : state;

  const retry = () => {
    manifestCache.delete(assetId);
    setState({ kind: "loading" });
    loadManifest(assetId).then(
      (manifest) => setState({ kind: "ready", assetId, manifest }),
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
        Loading enhanced pages…
      </p>
    );
  }

  if (effectiveState.kind === "error") {
    return <ErrorBanner message="Could not load the enhanced pages." onRetry={retry} />;
  }

  return (
    <div className="flex flex-col gap-6">
      {pageNumbers.map((pageNumber) => (
        <HtmlPage
          key={pageNumber}
          assetId={assetId}
          pageNumber={pageNumber}
          manifest={effectiveState.manifest}
        />
      ))}
    </div>
  );
}

function HtmlPage({
  assetId,
  pageNumber,
  manifest,
}: {
  assetId: string;
  pageNumber: number;
  manifest: AssetHtmlManifest;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const nearViewport = useNearViewport(containerRef);
  const [errored, setErrored] = useState(false);

  // React's synthetic onError prop doesn't fire for <iframe> the way it
  // does for <img>/<video>/<audio> (verified directly — React only
  // wires up direct, non-delegated listeners for a fixed set of tags,
  // and iframe isn't one of them) — a native listener on the real DOM
  // node is the only thing that actually observes it. Note this is still
  // a best-effort signal even so: many browsers don't fire "error" for
  // an iframe navigation that completed with an HTTP error status (the
  // iframe still "loaded", just the error page's own body) — there's no
  // fully reliable cross-browser way to detect that class of failure.
  useEffect(() => {
    if (!nearViewport) return undefined;
    const el = iframeRef.current;
    if (!el) return undefined;
    const handleError = () => setErrored(true);
    el.addEventListener("error", handleError);
    return () => el.removeEventListener("error", handleError);
  }, [nearViewport]);

  return (
    <div
      ref={containerRef}
      data-testid={`html-page-${pageNumber}`}
      className="mx-auto flex w-full items-center justify-center"
      // Sized from the manifest's known aspect ratio, scaled to
      // container width via CSS alone — no postMessage/onLoad round trip
      // to the (sandboxed, cross-document) iframe is needed since the
      // dimensions are already known up front.
      style={{ aspectRatio: `${manifest.width_px} / ${manifest.height_px}` }}
    >
      {!nearViewport ? (
        <span role="status" className="text-xs text-muted-foreground">
          Page {pageNumber}
        </span>
      ) : errored ? (
        <ErrorBanner message={`Could not render page ${pageNumber}.`} />
      ) : (
        // sandbox="" (present, empty) is the most restrictive sandboxing —
        // no allow-scripts, no allow-same-origin, etc. Inline CSS/fonts in
        // the served page still render under this; only active/privileged
        // capabilities (scripts, form submission, top navigation, ...) are
        // blocked. Text selection isn't gated by any sandbox token either.
        <iframe
          ref={iframeRef}
          title={`Page ${pageNumber}`}
          src={buildAssetHtmlPageUrl(assetId, pageNumber)}
          sandbox=""
          className="h-full w-full border-0"
        />
      )}
    </div>
  );
}
