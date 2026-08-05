"use client";

import { useState } from "react";
import { BookOpen, ChevronDown, Wrench } from "lucide-react";

import { useWorkspaceMode, type WorkspaceMode } from "@/lib/hooks/useWorkspaceMode";

const MODE_LABELS: Record<WorkspaceMode, string> = {
  learner: "Learner",
  instructor: "Instructor",
};

export default function WorkspaceModeMenu() {
  const { mode, setMode, disclosureSeen, markDisclosureSeen } = useWorkspaceMode();
  const [open, setOpen] = useState(false);
  const [confirmInstructor, setConfirmInstructor] = useState(false);

  function chooseMode(next: WorkspaceMode) {
    if (next === "instructor" && !disclosureSeen) {
      setOpen(false);
      setConfirmInstructor(true);
      return;
    }
    setMode(next);
    setOpen(false);
  }

  function continueToInstructorMode() {
    markDisclosureSeen();
    setMode("instructor");
    setConfirmInstructor(false);
  }

  return (
    <div className="relative">
      <div className="flex items-center gap-2">
        <span className="hidden text-xs font-semibold uppercase tracking-[0.08em] text-muted-foreground sm:inline">
          Workspace mode
        </span>
        <button
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label={`Workspace mode: ${MODE_LABELS[mode]}`}
          onClick={() => setOpen((current) => !current)}
          className="flex min-h-9 items-center gap-2 rounded-md border border-divider bg-surface px-3 py-1.5 text-sm font-semibold text-foreground transition-colors hover:bg-foreground/[0.07]"
        >
          {mode === "learner" ? (
            <BookOpen aria-hidden="true" className="h-4 w-4 text-accent-700" />
          ) : (
            <Wrench aria-hidden="true" className="h-4 w-4 text-accent-700" />
          )}
          <span>{MODE_LABELS[mode]}</span>
          <ChevronDown aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
        </button>
      </div>

      {open ? (
        <div
          role="menu"
          aria-label="Workspace mode"
          className="absolute right-0 z-30 mt-2 w-56 rounded-md border border-divider bg-surface-raised p-1 shadow-lg"
        >
          <button
            type="button"
            role="menuitemradio"
            aria-label="Learner"
            aria-checked={mode === "learner"}
            onClick={() => chooseMode("learner")}
            className="flex w-full items-start gap-2 rounded px-3 py-2 text-left text-sm hover:bg-foreground/[0.07]"
          >
            <BookOpen aria-hidden="true" className="mt-0.5 h-4 w-4 text-accent-700" />
            <span className="flex flex-col">
              <span className="font-semibold">Learner</span>
              <span className="text-xs text-muted-foreground">Study tools only</span>
            </span>
          </button>
          <button
            type="button"
            role="menuitemradio"
            aria-label="Instructor"
            aria-checked={mode === "instructor"}
            onClick={() => chooseMode("instructor")}
            className="flex w-full items-start gap-2 rounded px-3 py-2 text-left text-sm hover:bg-foreground/[0.07]"
          >
            <Wrench aria-hidden="true" className="mt-0.5 h-4 w-4 text-accent-700" />
            <span className="flex flex-col">
              <span className="font-semibold">Instructor</span>
              <span className="text-xs text-muted-foreground">Curriculum and validation</span>
            </span>
          </button>
        </div>
      ) : null}

      {confirmInstructor ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-foreground/30 p-4">
          <section
            role="dialog"
            aria-modal="true"
            aria-label="Instructor mode"
            className="w-full max-w-sm rounded-lg border border-divider bg-surface-raised p-5 shadow-xl"
          >
            <h2 className="font-heading text-lg text-foreground">Instructor mode</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Instructor mode shows curriculum review and validation tools. Learner study
              progress remains unchanged.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmInstructor(false)}
                className="rounded-md border border-divider px-3 py-2 text-sm font-semibold hover:bg-foreground/[0.07]"
              >
                Stay in learner mode
              </button>
              <button
                type="button"
                onClick={continueToInstructorMode}
                className="rounded-md bg-accent-700 px-3 py-2 text-sm font-semibold text-background hover:bg-accent-800"
              >
                Continue to instructor mode
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}
