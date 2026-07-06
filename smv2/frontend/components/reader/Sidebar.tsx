"use client";

import { useState } from "react";
import Link from "next/link";

import { chapterGroupKey, groupSectionsByChapter } from "@/lib/reader/chapterGroups";
import type { ChapterTestStats, ReaderSection } from "@/lib/reader/types";

export interface SidebarProps {
  courseId: string;
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
  /** Keyed by chapterGroupKey(group.label) — populated from list_chapters'
   * per-chapter test_stats once that endpoint is wired up; omitted (or a
   * missing key) just renders the "Test" link with no score yet. */
  chapterStats?: Record<string, ChapterTestStats>;
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

function formatScorePercent(score: number | null): string | null {
  return score === null ? null : `${Math.round(score * 100)}%`;
}

/**
 * The "Test" affordance's label/tooltip: once a score exists it takes
 * priority (unchanged); before that, surface how much practice material is
 * waiting so the link reads as more than a bare, unexplained "Test". Plain
 * "Test" only when there's neither a score nor any practice sections (a
 * chapter test can still be generated from lessons/content alone).
 */
function testLinkLabel(scoreLabel: string | null, practiceCount: number): string {
  if (scoreLabel) return `Test · ${scoreLabel}`;
  if (practiceCount > 0) {
    return `Test · ${practiceCount} practice sheet${practiceCount === 1 ? "" : "s"}`;
  }
  return "Test";
}

/**
 * Reader sidebar: sections grouped by chapter for scannability (a real
 * book can have 100+ flat sections, one row each). Grouping is presentation
 * only — `onSelect(index)` always receives the section's position in the
 * original FLAT `sections` prop (see `indexById` below), so CourseReader's
 * own reading-order navigation (j/k/arrows, activeIndex) is completely
 * untouched by how this component chooses to visually group things.
 *
 * Practice/answers sections are never listed as reading rows here — their
 * home is the chapter test page (the group's own "Test" link), not the
 * primary reading flow. They still count toward `indexById` (a deep link
 * or resumed session can land directly on one; CourseReader's own nav
 * skips them, so this doesn't affect keyboard traversal either way).
 */
export default function Sidebar({
  courseId,
  sections,
  activeSectionId,
  onSelect,
  lessonStatusOverrides,
  chapterStats,
}: SidebarProps) {
  // Which non-active groups the user has explicitly toggled open. The
  // active section's own group is *always* force-open (below) regardless
  // of this set — that's a live, render-time condition, not something
  // recorded here, so navigating away from a chapter that was never
  // manually toggled lets it collapse again rather than staying pinned
  // open forever. Starting empty means every group but the active one is
  // collapsed by default, which is the entire point of grouping at all.
  const [openGroups, setOpenGroups] = useState<Set<string>>(() => new Set());

  const indexById = new Map(sections.map((section, index) => [section.id, index]));
  const groups = groupSectionsByChapter(sections);
  const activeSection = sections.find((section) => section.id === activeSectionId);
  const activeGroupKey = chapterGroupKey(activeSection?.chapter_label ?? null);

  function toggleGroup(key: string, isActiveGroup: boolean) {
    if (isActiveGroup) return; // can't collapse the chapter you're currently reading
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <nav
      id="reader-sidebar"
      aria-label="Chapter outline"
      className="flex w-72 shrink-0 flex-col overflow-y-auto border-r border-border bg-background/60 py-2"
    >
      <ul>
        {groups.map((group) => {
          const isActiveGroup = group.key === activeGroupKey;
          const open = isActiveGroup || openGroups.has(group.key);
          const listId = `chapter-group-${group.key}`;
          const stats = chapterStats?.[group.key];
          const scoreLabel = stats ? formatScorePercent(stats.best_score) : null;
          const contentSections = group.sections.filter((section) => section.kind === "content");
          const practiceCount = group.sections.filter((section) => section.kind === "practice").length;
          const testLabel = testLinkLabel(scoreLabel, practiceCount);

          return (
            <li key={group.key}>
              <div className="flex items-center gap-1 py-1 pl-3 pr-3">
                <button
                  type="button"
                  onClick={() => toggleGroup(group.key, isActiveGroup)}
                  aria-expanded={open}
                  aria-controls={listId}
                  className="flex flex-1 items-center gap-1.5 truncate rounded px-1 py-1 text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:bg-muted-foreground/10"
                >
                  <span aria-hidden="true" className="text-[10px]">
                    {open ? "▾" : "▸"}
                  </span>
                  <span className="truncate">{group.displayLabel}</span>
                </button>
                {group.label !== null && (
                  <Link
                    href={`/course/${courseId}/chapter/${encodeURIComponent(group.label)}/test`}
                    title={testLabel}
                    className="shrink-0 rounded border border-border px-1.5 py-0.5 text-[10px] font-medium hover:bg-muted-foreground/10"
                  >
                    {testLabel}
                  </Link>
                )}
              </div>
              {open && (
                <ul id={listId}>
                  {contentSections.map((section, sectionIndex) => {
                    const index = indexById.get(section.id);
                    if (index === undefined) return null;
                    const active = section.id === activeSectionId;
                    const lessonDisplayStatus =
                      lessonStatusOverrides?.[section.id] ?? section.lesson_status;
                    return (
                      <li key={section.id}>
                        <button
                          type="button"
                          aria-current={active ? "true" : undefined}
                          onClick={() => onSelect(index)}
                          className={`block w-full border-l-2 py-1.5 pl-4 pr-3 text-left text-sm transition-colors ${
                            active
                              ? "border-accent font-medium text-accent"
                              : "border-transparent hover:bg-muted-foreground/10"
                          }`}
                        >
                          <span className="flex items-center gap-2">
                            <LessonDot status={lessonDisplayStatus} />
                            <span className="shrink-0 text-muted-foreground">
                              {sectionIndex + 1}.
                            </span>
                            <span className="truncate">{section.title}</span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
