"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { useWorkspaceMode } from "@/lib/hooks/useWorkspaceMode";

interface WorkspaceModeGateProps {
  courseId: string;
  children: ReactNode;
}

export default function WorkspaceModeGate({ courseId, children }: WorkspaceModeGateProps) {
  const { mode, setMode, markDisclosureSeen } = useWorkspaceMode();

  if (mode === "instructor") {
    return <>{children}</>;
  }

  function switchToInstructorMode() {
    markDisclosureSeen();
    setMode("instructor");
  }

  return (
    <section
      role="region"
      aria-labelledby="workspace-mode-gate-title"
      className="mx-auto flex min-h-[55vh] w-full max-w-2xl flex-col justify-center px-4 py-16"
    >
      <div className="rounded-lg border border-divider bg-surface-raised p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground">
          Learner mode
        </p>
        <h1
          id="workspace-mode-gate-title"
          className="mt-2 font-heading text-2xl text-foreground"
        >
          Instructor workspace is hidden
        </h1>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">
          Learner mode keeps curriculum review and diagnostics out of the main study
          flow. Workspace mode is a local display preference, not a security
          boundary.
        </p>
        <div className="mt-6 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={switchToInstructorMode}
            className="rounded-md bg-accent-700 px-4 py-2 text-sm font-heading text-background transition-colors hover:bg-accent-800 active:bg-accent-900"
          >
            Switch to Instructor mode
          </button>
          <Link
            href={`/course/${courseId}`}
            className="inline-flex items-center justify-center rounded-md border border-border bg-surface px-4 py-2 text-sm font-heading transition-colors hover:bg-foreground/[0.07] active:bg-foreground/[0.14]"
          >
            Back to course
          </Link>
        </div>
      </div>
    </section>
  );
}
