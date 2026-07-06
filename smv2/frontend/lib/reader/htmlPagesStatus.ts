"use client";

/**
 * Resolves an asset's "enhanced" (pdf2htmlEX HTML) pages status, reading
 * AssetOut.html_status off the already-existing, already-typed
 * listAssets() response — no dedicated per-asset endpoint needed. Cached
 * per course (one listAssets call covers every asset in it, rather than
 * one fetch per individual asset id).
 */

import { useEffect, useState } from "react";

import { listAssets, type AssetOut } from "@/lib/api/client";

export type AssetHtmlStatus = AssetOut["html_status"];

const courseAssetsCache = new Map<string, Promise<AssetOut[]>>();

function loadCourseAssets(courseId: string): Promise<AssetOut[]> {
  let cached = courseAssetsCache.get(courseId);
  if (!cached) {
    cached = listAssets(courseId).then(({ data }) => data ?? []);
    // A failed fetch shouldn't be cached forever as an empty dead end —
    // a later call for the same course should retry.
    cached.catch(() => courseAssetsCache.delete(courseId));
    courseAssetsCache.set(courseId, cached);
  }
  return cached;
}

export async function getAssetHtmlStatus(
  courseId: string,
  assetId: string,
): Promise<AssetHtmlStatus> {
  const assets = await loadCourseAssets(courseId);
  const asset = assets.find((candidate) => candidate.id === assetId);
  return asset?.html_status ?? "none";
}

/**
 * Reactive wrapper around getAssetHtmlStatus. Defaults to (and falls back
 * to) "none" — the safe "just use pdf.js" state — both before the lookup
 * resolves and if assetId changes again before it does; the result is
 * tagged with the assetId it resolved for so a stale answer for a
 * previous section can never be shown as if it were the current one's
 * (the previous section's own asset simply not being ready for its
 * *own* enhanced view is a different thing than seeing that answer
 * flash on an unrelated new section that hasn't been checked yet).
 */
export function useAssetHtmlStatus(courseId: string, assetId: string): AssetHtmlStatus {
  const [state, setState] = useState<{ assetId: string; status: AssetHtmlStatus }>({
    assetId: "",
    status: "none",
  });

  useEffect(() => {
    let active = true;
    getAssetHtmlStatus(courseId, assetId).then((status) => {
      if (active) setState({ assetId, status });
    });
    return () => {
      active = false;
    };
  }, [courseId, assetId]);

  return state.assetId === assetId ? state.status : "none";
}
