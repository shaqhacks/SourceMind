"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { getSkillStatus, startCurriculumExtraction, type SkillStatusOut } from "@/lib/api/client";

export interface SkillMapStatusBannerProps {
  courseId: string;
}

const POLL_MS = 4000;

/**
 * Slim reader strip for the skill-map lifecycle (ADR-030). Auto-queue on
 * upload means the map is usually "generating" the first time the reader
 * mounts after a new course. Polls only while a generation is in flight,
 * then settles into a link to the editor (draft ready) or a retry (failed).
 * Renders nothing once the map is published or absent-and-idle, so it never
 * adds noise to a course that doesn't need it.
 */
export default function SkillMapStatusBanner({ courseId }: SkillMapStatusBannerProps) {
  const [status, setStatus] = useState<SkillStatusOut | null>(null);
  const [retrying, setRetrying] = useState(false);

  const refresh = useCallback(async (isActive: () => boolean) => {
    const { data } = await getSkillStatus(courseId);
    if (isActive() && data) setStatus(data);
  }, [courseId]);

  useEffect(() => {
    let active = true;
    void refresh(() => active);
    return () => {
      active = false;
    };
  }, [refresh]);

  useEffect(() => {
    if (status?.phase !== "generating" && status?.phase !== "none") return;
    let active = true;
    const timer = setInterval(() => void refresh(() => active), POLL_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [status?.phase, refresh]);

  async function retry() {
    setRetrying(true);
    await startCurriculumExtraction(courseId);
    setRetrying(false);
    void refresh(() => true);
  }

  if (!status) return null;
  if (status.phase === "published" || status.phase === "none") return null;

  if (status.phase === "generating") {
    return (
      <div className="flex items-center justify-center gap-2 border-b border-divider bg-accent-soft px-4 py-2 text-sm">
        <span className="text-accent-800">Generating your skill map…</span>
        <span className="text-muted-foreground">
          You can keep reading — this finishes in the background.
        </span>
      </div>
    );
  }

  if (status.phase === "failed") {
    return (
      <div className="flex flex-wrap items-center justify-center gap-2 border-b border-status-serious/30 bg-status-serious-soft px-4 py-2 text-sm">
        <span className="text-status-serious">Skill map generation failed.</span>
        <button
          type="button"
          onClick={() => void retry()}
          disabled={retrying}
          className="font-semibold text-status-serious underline disabled:opacity-45"
        >
          {retrying ? "Retrying…" : "Retry"}
        </button>
        <span className="text-muted-foreground">or</span>
        <Link href={`/course/${courseId}/skills/edit`} className="font-semibold text-status-serious underline">
          open the editor
        </Link>
      </div>
    );
  }

  // draft_ready
  return (
    <div className="flex flex-wrap items-center justify-center gap-2 border-b border-divider bg-accent-soft px-4 py-2 text-sm">
      <span className="text-accent-800">Skill map draft ready to review.</span>
      <Link
        href={`/course/${courseId}/skills/edit`}
        className="font-semibold text-accent-800 underline"
      >
        Review &amp; publish
      </Link>
    </div>
  );
}
