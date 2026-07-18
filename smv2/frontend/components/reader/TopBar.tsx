"use client";

import { useCallback, useRef, useState } from "react";

import TypographyControls from "@/components/TypographyControls";
import { useDialogFocus } from "@/lib/hooks/useDialogFocus";
import { useDismissOnOutsideOrEscape } from "@/lib/hooks/useDismissOnOutsideOrEscape";
import { useNarrowViewport } from "@/lib/hooks/useNarrowViewport";
import type { ViewMode } from "@/lib/reader/types";

import GenerateAllLessons from "./GenerateAllLessons";
import QuizzesPanel from "./QuizzesPanel";

// Below Tailwind's `lg` breakpoint (min-width: 1024px) the three mid-bar
// actions (Edit outline, GenerateAllLessons, QuizzesPanel) collapse into an
// overflow menu; at/above it they sit inline. 1023 is the max-width
// complement of that min-width boundary.
//
// They render in exactly ONE slot at a time (JS switch, not a `hidden
// lg:flex` / `lg:hidden` CSS pair): GenerateAllLessons holds per-instance
// job-watch state (LessonJobWatcher children) and QuizzesPanel holds its own
// job/SSE state AND emits a fixed id="quizzes-panel". Two simultaneously
// mounted copies would duplicate that DOM id and split their state, so the
// inline-vs-menu choice is made in JS via useNarrowViewport (SSR-safe:
// useSyncExternalStore returns false on the server, same idiom as useTheme).
const OVERFLOW_BREAKPOINT_PX = 1023;

export interface TopBarProps {
  courseId: string;
  courseTitle: string;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onLessonSectionSettled: (sectionId: string, status: "ready" | "failed") => void;
  chatOpen: boolean;
  onToggleChat: () => void;
  /** Whether the CSS Custom Highlight API is supported — the reader's
   * Global Constraint is that ALL annotation UI (including the Notes
   * panel, which is nothing but a list of highlights) is hidden when it
   * isn't. Computed once by CourseReader (see
   * lib/annotations/useHighlightPainter's isHighlightApiSupported) and
   * passed down so this component stays presentational. */
  notesSupported: boolean;
  notesOpen: boolean;
  onToggleNotes: () => void;
  onOpenOutlineEditor: () => void;
  viewMode: ViewMode;
  pagesAvailable: boolean;
  onChangeViewMode: (mode: ViewMode) => void;
}

const VIEW_OPTIONS: { mode: ViewMode; label: string }[] = [
  { mode: "source", label: "Source" },
  { mode: "pages", label: "Pages" },
  { mode: "lesson", label: "Lesson" },
];

export default function TopBar({
  courseId,
  courseTitle,
  sidebarCollapsed,
  onToggleSidebar,
  onLessonSectionSettled,
  chatOpen,
  onToggleChat,
  notesSupported,
  notesOpen,
  onToggleNotes,
  onOpenOutlineEditor,
  viewMode,
  pagesAvailable,
  onChangeViewMode,
}: TopBarProps) {
  const isNarrow = useNarrowViewport(OVERFLOW_BREAKPOINT_PX);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  // Non-modal popover focus management (same pattern as QuizzesPanel):
  // moves focus into the panel on open, restores it to the ⋯ trigger on
  // close. `trap: false` — this popover doesn't hold focus captive.
  const menuPanelRef = useDialogFocus<HTMLDivElement>(menuOpen, { trap: false });
  const closeMenu = useCallback(() => setMenuOpen(false), []);
  // Signature is (open, onClose, containerRef) — containerRef wraps both the
  // trigger and the panel so clicking the trigger to toggle isn't treated as
  // an "outside" dismissal.
  useDismissOnOutsideOrEscape(menuOpen, closeMenu, menuRef);

  // The three mid-bar actions, rendered identically inline or in the menu.
  // In the menu, selecting "Edit outline" also closes the menu; the two
  // stateful children carry their own triggers/popovers unchanged.
  const midControls = (variant: "inline" | "menu") => (
    <>
      <button
        type="button"
        onClick={() => {
          if (variant === "menu") setMenuOpen(false);
          onOpenOutlineEditor();
        }}
        className={
          variant === "menu"
            ? "rounded-md border border-border px-2 py-1 text-left text-sm hover:bg-muted-foreground/10"
            : "rounded-md border border-border px-2 py-1 text-sm"
        }
      >
        Edit outline
      </button>
      <GenerateAllLessons courseId={courseId} onSectionSettled={onLessonSectionSettled} />
      <QuizzesPanel courseId={courseId} />
    </>
  );

  return (
    <div className="flex items-center gap-2 border-b border-border px-4 py-2 text-sm">
      <button
        type="button"
        onClick={onToggleSidebar}
        aria-expanded={!sidebarCollapsed}
        aria-controls="reader-sidebar"
        aria-label={sidebarCollapsed ? "Show outline" : "Hide outline"}
        className="rounded-md border border-border px-2 py-1 text-sm hover:bg-muted-foreground/10"
      >
        ☰
      </button>
      <h1 className="min-w-0 flex-1 truncate text-sm font-medium">{courseTitle}</h1>
      <div role="group" aria-label="Reading view" className="flex overflow-hidden rounded-md border border-border text-sm">
        {VIEW_OPTIONS.map(({ mode, label }) => {
          const disabled = mode === "pages" && !pagesAvailable;
          return (
            <button
              key={mode}
              type="button"
              aria-pressed={viewMode === mode}
              disabled={disabled}
              title={disabled ? "Re-ingest this course to enable original pages" : undefined}
              onClick={() => onChangeViewMode(mode)}
              className={`px-2 py-1 disabled:cursor-not-allowed disabled:opacity-40 ${
                viewMode === mode ? "bg-accent/15 font-medium text-accent" : "hover:bg-muted-foreground/10"
              }`}
            >
              {label}
            </button>
          );
        })}
      </div>
      {isNarrow ? (
        <div ref={menuRef} className="relative">
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            aria-expanded={menuOpen}
            aria-haspopup="true"
            aria-label="More actions"
            className="rounded-md border border-border px-2 py-1 text-sm hover:bg-muted-foreground/10"
          >
            ⋯
          </button>
          {menuOpen && (
            <div
              ref={menuPanelRef}
              role="group"
              aria-label="More actions"
              tabIndex={-1}
              className="absolute right-0 top-full z-30 mt-1 flex w-56 flex-col gap-2 rounded-lg border border-border bg-background p-3 shadow-lg"
            >
              {midControls("menu")}
            </div>
          )}
        </div>
      ) : (
        <div className="flex items-center gap-2">{midControls("inline")}</div>
      )}
      <button
        type="button"
        onClick={onToggleChat}
        aria-pressed={chatOpen}
        aria-label={chatOpen ? "Close chat" : "Open chat"}
        className="rounded-md border border-border px-2 py-1 text-sm"
      >
        Chat
      </button>
      {notesSupported && (
        <button
          type="button"
          onClick={onToggleNotes}
          aria-pressed={notesOpen}
          aria-label={notesOpen ? "Close notes" : "Open notes"}
          className="rounded-md border border-border px-2 py-1 text-sm"
        >
          Notes
        </button>
      )}
      <TypographyControls />
    </div>
  );
}
