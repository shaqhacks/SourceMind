"use client";

import { useEffect, useState } from "react";

import { getJob } from "@/lib/api/client";

/**
 * JobEvent (the SSE snapshot) carries no error text — only {id, status,
 * progress} — so surfacing the actual failure message needs a follow-up
 * plain REST fetch. Shared by every job-driven CTA that shows "Generation
 * failed: {message}" once its watched job fails (CardsCTA, QuizzesPanel,
 * ChapterDeckCard, GenerateTestCard), which each used to inline this same
 * failureInfo state + effect + derived-message logic separately.
 *
 * The returned message is scoped to `jobId` — the CURRENT job being
 * watched — via the same "tagged with the id it belongs to" idiom as
 * useJobEvents' own internal state, so a fetch for a since-abandoned job
 * can never leak its message onto a newer one.
 */
export function useJobFailureMessage(jobFailed: boolean, jobId: string | null): string | null {
  const [failureInfo, setFailureInfo] = useState<{ jobId: string; message: string | null } | null>(
    null,
  );

  useEffect(() => {
    if (!jobFailed || !jobId) return;
    let active = true;
    getJob(jobId).then(({ data }) => {
      if (active) setFailureInfo({ jobId, message: data?.error ?? null });
    });
    return () => {
      active = false;
    };
  }, [jobFailed, jobId]);

  return failureInfo?.jobId === jobId ? failureInfo.message : null;
}
