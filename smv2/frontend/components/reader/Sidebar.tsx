import type { ReaderSection } from "@/lib/reader/types";

export interface SidebarProps {
  sections: ReaderSection[];
  activeSectionId: string;
  onSelect: (index: number) => void;
  /**
   * Patches over list_sections' lesson_status for sections whose
   * generation has settled since the list was fetched (also carries the
   * synthetic "stale" value, which list_sections doesn't expose at all —
   * see LessonPane). Keyed by section id.
   */
  lessonStatusOverrides?: Record<string, string>;
}

// Shades picked so each dot clears the WCAG 1.4.11 3:1 non-text contrast
// minimum against BOTH themes' background with one class (no dark:
// override needed) — e.g. bg-green-700 is 5.0:1 on white and 4.0:1 on
// near-black. "none" is deliberately left low-contrast: it represents
// absence, and the section's own "Generate lesson" CTA is the real,
// higher-contrast indicator of that state.
const LESSON_DOT_CONFIG: Record<string, { label: string; className: string }> = {
  none: { label: "No lesson yet", className: "bg-muted-foreground/30" },
  queued: { label: "Lesson queued", className: "bg-blue-600" },
  generating: { label: "Lesson generating", className: "bg-blue-500 animate-pulse" },
  ready: { label: "Lesson ready", className: "bg-green-700" },
  failed: { label: "Lesson generation failed", className: "bg-red-500" },
  stale: { label: "Lesson needs regeneration", className: "bg-amber-700" },
};

function LessonDot({ status }: { status: string }) {
  const config = LESSON_DOT_CONFIG[status] ?? LESSON_DOT_CONFIG.none;
  return (
    <span
      role="img"
      aria-label={config.label}
      title={config.label}
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${config.className}`}
    />
  );
}

export default function Sidebar({
  sections,
  activeSectionId,
  onSelect,
  lessonStatusOverrides,
}: SidebarProps) {
  return (
    <nav
      id="reader-sidebar"
      aria-label="Chapter outline"
      className="flex w-64 shrink-0 flex-col overflow-y-auto border-r border-border"
    >
      <ul>
        {sections.map((section, index) => {
          const active = section.id === activeSectionId;
          const lessonDisplayStatus = lessonStatusOverrides?.[section.id] ?? section.lesson_status;
          return (
            <li key={section.id}>
              <button
                type="button"
                aria-current={active ? "true" : undefined}
                onClick={() => onSelect(index)}
                className={`block w-full px-4 py-2 text-left text-sm ${
                  active
                    ? "bg-accent/10 font-medium text-accent"
                    : "hover:bg-muted-foreground/10"
                }`}
              >
                <span className="flex items-center gap-2">
                  <LessonDot status={lessonDisplayStatus} />
                  <span className="truncate">{section.title}</span>
                </span>
                {section.page_start !== null && section.page_end !== null ? (
                  <span className="block text-xs text-muted-foreground">
                    p.{section.page_start}–{section.page_end}
                  </span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
