"use client";

import { useCallback, useRef, useState } from "react";
import { MessageSquare, PanelLeft, StickyNote } from "lucide-react";

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

// Shared secondary-control shape for this bar (design system: surface fill
// + 24%-ink border, 13px). Not <Button> from components/ui: these sit in a
// dense chrome row and use the body face, where Button's display-face
// heading treatment reads as oversized.
const SECONDARY_CONTROL =
  "rounded-md border border-border bg-surface-raised px-3 py-1.5 text-[13px] font-medium transition-colors hover:bg-foreground/[0.07] active:bg-foreground/[0.14]";

// Square icon-button variant of the same treatment.
const ICON_CONTROL =
  "flex h-8 w-8 items-center justify-center rounded-md border border-border bg-surface-raised transition-colors hover:bg-foreground/[0.07] active:bg-foreground/[0.14]";

export interface TopBarProps {
  courseId: string;
  courseTitle: string;
  /** Breadcrumb tail: the section being read, and its chapter when the
   * section carries one. Display-only — navigation is unchanged. */
  chapterLabel: string | null;
  sectionTitle: string;
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
  chapterLabel,
  sectionTitle,
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
          variant === "menu" ? `${SECONDARY_CONTROL} text-left` : SECONDARY_CONTROL
        }
      >
        Edit outline
      </button>
      <GenerateAllLessons courseId={courseId} onSectionSettled={onLessonSectionSettled} />
      <QuizzesPanel courseId={courseId} />
    </>
  );

  return (
    <div className="flex items-center gap-3 border-b border-divider px-5 py-2.5 text-sm">
      <button
        type="button"
        onClick={onToggleSidebar}
        aria-expanded={!sidebarCollapsed}
        aria-controls="reader-sidebar"
        aria-label={sidebarCollapsed ? "Show outline" : "Hide outline"}
        className={ICON_CONTROL}
      >
        <PanelLeft aria-hidden="true" className="h-4 w-4" strokeWidth={2.75} />
      </button>
      {/* Breadcrumb, not a heading: the reading column's own chapter <h2>
          (and any h1 inside the source text) owns this page's document
          outline — same rule SiteHeader follows for the brand. */}
      <p className="min-w-0 flex-1 truncate text-[13px] text-muted-foreground">
        {courseTitle}
        <span aria-hidden="true" className="px-1.5 opacity-50">
          /
        </span>
        <strong className="font-semibold text-foreground">
          {chapterLabel ? `${chapterLabel} · ${sectionTitle}` : sectionTitle}
        </strong>
      </p>
      <div
        role="group"
        aria-label="Reading view"
        className="flex shrink-0 gap-0.5 rounded-md border border-border bg-surface-raised p-0.5 text-[13px]"
      >
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
              className={`rounded-[6px] px-3 py-1 transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                viewMode === mode
                  ? "bg-accent-700 font-semibold text-background"
                  : "hover:bg-foreground/[0.07]"
              }`}
            >
              {label}
            </button>
          );
        })}
      </div>
      {isNarrow ? (
        <div ref={menuRef} className="relative shrink-0">
          <button
            type="button"
            onClick={() => setMenuOpen((open) => !open)}
            aria-expanded={menuOpen}
            aria-haspopup="true"
            aria-label="More actions"
            className={ICON_CONTROL}
          >
            <span aria-hidden="true" className="leading-none">
              ⋯
            </span>
          </button>
          {menuOpen && (
            <div
              ref={menuPanelRef}
              role="group"
              aria-label="More actions"
              tabIndex={-1}
              className="absolute right-0 top-full z-30 mt-1.5 flex w-56 flex-col gap-2 rounded-lg border border-divider bg-surface-raised p-3 shadow-md"
            >
              {midControls("menu")}
            </div>
          )}
        </div>
      ) : (
        <div className="flex shrink-0 items-center gap-2">{midControls("inline")}</div>
      )}
      {/* Chat / Notes stay two independent toggles (they are mutually
          exclusive right-side panels, not a tab group) — the mock's single
          Chat/Cards/Notes segmented panel is deferred, see the reader
          notes in the redesign plan. */}
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          onClick={onToggleChat}
          aria-pressed={chatOpen}
          aria-label={chatOpen ? "Close chat" : "Open chat"}
          className={
            chatOpen
              ? `${ICON_CONTROL} border-accent-700 bg-accent-700 text-background hover:bg-accent-800`
              : ICON_CONTROL
          }
        >
          <MessageSquare aria-hidden="true" className="h-4 w-4" strokeWidth={2.75} />
        </button>
        {notesSupported && (
          <button
            type="button"
            onClick={onToggleNotes}
            aria-pressed={notesOpen}
            aria-label={notesOpen ? "Close notes" : "Open notes"}
            className={
              notesOpen
                ? `${ICON_CONTROL} border-accent-700 bg-accent-700 text-background hover:bg-accent-800`
                : ICON_CONTROL
            }
          >
            <StickyNote aria-hidden="true" className="h-4 w-4" strokeWidth={2.75} />
          </button>
        )}
        <TypographyControls />
      </div>
    </div>
  );
}
