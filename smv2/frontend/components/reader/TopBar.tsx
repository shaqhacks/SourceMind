import ThemeToggle from "@/components/ThemeToggle";
import TypographyControls from "@/components/TypographyControls";
import type { ViewMode } from "@/lib/reader/types";

import GenerateAllLessons from "./GenerateAllLessons";
import QuizzesPanel from "./QuizzesPanel";

export interface TopBarProps {
  courseId: string;
  courseTitle: string;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onLessonSectionSettled: (sectionId: string, status: "ready" | "failed") => void;
  chatOpen: boolean;
  onToggleChat: () => void;
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
  onOpenOutlineEditor,
  viewMode,
  pagesAvailable,
  onChangeViewMode,
}: TopBarProps) {
  return (
    <div className="flex items-center gap-3 border-b border-border px-4 py-3">
      <button
        type="button"
        onClick={onToggleSidebar}
        aria-expanded={!sidebarCollapsed}
        aria-controls="reader-sidebar"
        aria-label={sidebarCollapsed ? "Show outline" : "Hide outline"}
        className="rounded-md border border-border px-2 py-1 text-sm"
      >
        ☰
      </button>
      <h1 className="min-w-0 flex-1 truncate text-sm font-semibold">{courseTitle}</h1>
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
      <button
        type="button"
        onClick={onOpenOutlineEditor}
        className="rounded-md border border-border px-2 py-1 text-sm"
      >
        Edit outline
      </button>
      <GenerateAllLessons courseId={courseId} onSectionSettled={onLessonSectionSettled} />
      <QuizzesPanel courseId={courseId} />
      <button
        type="button"
        onClick={onToggleChat}
        aria-pressed={chatOpen}
        aria-label={chatOpen ? "Close chat" : "Open chat"}
        className="rounded-md border border-border px-2 py-1 text-sm"
      >
        Chat
      </button>
      <TypographyControls />
      <ThemeToggle />
    </div>
  );
}
