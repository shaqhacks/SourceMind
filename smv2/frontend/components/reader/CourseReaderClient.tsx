"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";

import ErrorBanner from "@/components/ErrorBanner";
import { getCourse, getProgress, listSections, type ProgressOut } from "@/lib/api/client";
import type { ReaderCourse } from "@/lib/reader/types";

// The reader is entirely localStorage/keyboard-driven (theme, typography,
// focus) — content genuinely worth SSR-ing today doesn't outweigh the
// hydration-mismatch risk that state carries. `ssr: false` skips server
// rendering for this subtree entirely, so there is nothing for a
// client-only preference to mismatch against.
//
// Next.js only allows `dynamic(..., { ssr: false })` inside a Client
// Component (it throws if called from a Server Component), which is why
// this thin wrapper exists instead of calling it directly from
// app/course/[courseId]/page.tsx.
const CourseReader = dynamic(() => import("./CourseReader"), {
  ssr: false,
  loading: () => (
    <div className="flex flex-1 items-center justify-center p-8 text-sm text-muted-foreground">
      Loading reader…
    </div>
  ),
});

export interface CourseReaderClientProps {
  courseId: string;
}

interface FetchError {
  status?: number;
  message: string;
}

function describeError(status: number | undefined, action: string): FetchError {
  if (status === undefined) {
    return { message: `${action}: could not reach the API. Is the backend running?` };
  }
  return { status, message: `${action} failed (HTTP ${status}).` };
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; error: FetchError }
  | { kind: "ready"; course: ReaderCourse; progress: ProgressOut };

async function fetchReaderData(courseId: string): Promise<LoadState> {
  const [courseResult, sectionsResult, progressResult] = await Promise.all([
    getCourse(courseId),
    listSections(courseId),
    getProgress(courseId),
  ]);

  if (!courseResult.data) {
    return { kind: "error", error: describeError(courseResult.status, "Loading course") };
  }
  if (!sectionsResult.data) {
    return { kind: "error", error: describeError(sectionsResult.status, "Loading chapters") };
  }
  if (!progressResult.data) {
    return { kind: "error", error: describeError(progressResult.status, "Loading progress") };
  }

  return {
    kind: "ready",
    course: {
      id: courseResult.data.id,
      title: courseResult.data.title,
      sections: sectionsResult.data,
    },
    progress: progressResult.data,
  };
}

/**
 * Fetches course + its sections + saved progress, in parallel, and renders
 * loading/error/empty states around the actual reader shell. Section body
 * text is deliberately not fetched here — CourseReader lazy-loads a
 * section's body via get_section only once it becomes the active chapter.
 */
export default function CourseReaderClient({ courseId }: CourseReaderClientProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  // Retry-button callback: no unmount guard needed, it only ever runs from
  // a user click on an already-mounted ErrorBanner.
  const retry = useCallback(async () => {
    setState({ kind: "loading" });
    setState(await fetchReaderData(courseId));
  }, [courseId]);

  // Mount-only fetch: setState happens inside the .then() callback rather
  // than through `retry` directly, so an unmount during the in-flight
  // request can't set state on a gone component (same pattern as
  // app/page.tsx's mount effect).
  useEffect(() => {
    let active = true;
    fetchReaderData(courseId).then((result) => {
      if (active) setState(result);
    });
    return () => {
      active = false;
    };
  }, [courseId]);

  if (state.kind === "loading") {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-sm text-muted-foreground">
        Loading course…
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div className="flex flex-1 items-center justify-center p-8">
        <div className="w-full max-w-md">
          <ErrorBanner status={state.error.status} message={state.error.message} onRetry={retry} />
        </div>
      </div>
    );
  }

  if (state.course.sections.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center text-sm text-muted-foreground">
        <p>&ldquo;{state.course.title}&rdquo; doesn&apos;t have any chapters yet.</p>
        <p>
          If you just uploaded a PDF, ingest may still be running — check its status on the{" "}
          <Link href="/" className="font-medium text-accent underline">
            dashboard
          </Link>
          .
        </p>
      </div>
    );
  }

  return <CourseReader course={state.course} initialProgress={state.progress} />;
}
