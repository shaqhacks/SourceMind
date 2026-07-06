import ThemeToggle from "@/components/ThemeToggle";
import TypographyControls from "@/components/TypographyControls";

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
}

export default function TopBar({
  courseId,
  courseTitle,
  sidebarCollapsed,
  onToggleSidebar,
  onLessonSectionSettled,
  chatOpen,
  onToggleChat,
  onOpenOutlineEditor,
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
