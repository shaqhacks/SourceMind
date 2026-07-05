import type { ReaderSection } from "@/lib/reader/types";

export interface SidebarProps {
  sections: ReaderSection[];
  activeSectionId: string;
  onSelect: (index: number) => void;
}

export default function Sidebar({ sections, activeSectionId, onSelect }: SidebarProps) {
  return (
    <nav
      id="reader-sidebar"
      aria-label="Chapter outline"
      className="flex w-64 shrink-0 flex-col overflow-y-auto border-r border-border"
    >
      <ul>
        {sections.map((section, index) => {
          const active = section.id === activeSectionId;
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
                <span className="block truncate">{section.title}</span>
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
