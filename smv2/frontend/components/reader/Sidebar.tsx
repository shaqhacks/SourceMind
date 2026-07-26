"use client";

import { useState } from "react";
import Link from "next/link";

import ProgressBar from "@/components/ui/ProgressBar";
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

/**
 * Reading-position marker, per the redesign's contents rows: an accent ring
 * on the section being read, a faint neutral ring on every other one.
 *
 * The mock also specifies a sage-filled ✓ for "read" — deliberately not
 * implemented: this component only knows which section is CURRENT (from
 * `activeSectionId`), and nothing in the reader's data model records which
 * sections have been read. Inventing that from position in the list would
 * be a fabricated state, so unread/current are the only two rendered.
 * `aria-hidden` because `aria-current` on the row button already conveys
 * "this is the one you're on" to assistive tech.
 */
function PositionDot({ current }: { current: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={`h-[18px] w-[18px] shrink-0 rounded-full ${
        current ? "border-2 border-accent" : "border-[1.5px] border-neutral-400"
      }`}
    />
  );
}

// Chapter-row "Test" tag. Raw span/link classes rather than <Badge>: Badge
// prefixes a decorative glyph, which would land inside this link's
// accessible name and break the `/^test/`-anchored queries the sidebar
// tests use.
const TEST_TAG_BASE =
  "shrink-0 rounded-[6px] px-2 py-0.5 text-[10px] font-medium transition-colors";

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

  // Position of the active section within its own chapter's reading rows —
  // the only progress-shaped figure this component can derive honestly (see
  // PositionDot's note on why "read" state isn't available). Zero when the
  // active section isn't a content row (a deep-linked practice/answers
  // section), which suppresses the callout entirely.
  const activeGroup = groups.find((group) => group.key === activeGroupKey);
  const activeGroupContent =
    activeGroup?.sections.filter((section) => section.kind === "content") ?? [];
  const positionInChapter =
    activeGroupContent.findIndex((section) => section.id === activeSectionId) + 1;

  return (
    <nav
      id="reader-sidebar"
      aria-label="Chapter outline"
      className="flex min-h-0 w-[300px] shrink-0 flex-col gap-0.5 overflow-y-auto border-r border-divider p-4"
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
              <div className="flex items-center gap-2 px-2 py-1.5">
                <button
                  type="button"
                  onClick={() => toggleGroup(group.key, isActiveGroup)}
                  aria-expanded={open}
                  aria-controls={listId}
                  className={`flex flex-1 items-center gap-2 truncate rounded-sm px-1 py-0.5 text-left text-[11px] font-bold uppercase tracking-[0.06em] transition-colors hover:bg-foreground/[0.05] ${
                    isActiveGroup ? "text-foreground" : "text-neutral-600"
                  }`}
                >
                  <span aria-hidden="true" className="text-[10px] leading-none">
                    {open ? "▾" : "▸"}
                  </span>
                  <span className="truncate">{group.displayLabel}</span>
                </button>
                {group.label !== null && (
                  <Link
                    href={`/course/${courseId}/chapter/${encodeURIComponent(group.label)}/test`}
                    title={testLabel}
                    className={`${TEST_TAG_BASE} ${
                      isActiveGroup
                        ? "bg-accent-soft text-accent-800 hover:bg-accent-200"
                        : "bg-neutral-100 text-neutral-800 hover:bg-neutral-200"
                    }`}
                  >
                    {testLabel}
                  </Link>
                )}
              </div>
              {open && (
                <ul id={listId} className="flex flex-col gap-px pl-2.5">
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
                          className={`flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-left text-[13.5px] transition-colors ${
                            active
                              ? "bg-surface-raised font-semibold shadow-sm"
                              : "opacity-70 hover:bg-foreground/[0.05] hover:opacity-100"
                          }`}
                        >
                          <PositionDot current={active} />
                          <span className="shrink-0 text-muted-foreground">
                            {sectionIndex + 1}.
                          </span>
                          <span className="min-w-0 flex-1 truncate">{section.title}</span>
                          <LessonDot status={lessonDisplayStatus} />
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
      {/* Bottom-pinned chapter callout. Deliberately narrower than the
          mock's: it shows only where you are in the chapter, because that
          is the one figure derivable from this component's props. The
          mock's "N sections read" and "N cards due" have no backing data
          here (no per-section read flag, no due counts) and are omitted
          rather than approximated. */}
      {positionInChapter > 0 && activeGroupContent.length > 0 && (
        <div className="mt-auto rounded-lg bg-sage-100 p-3.5 text-[13px] leading-relaxed">
          <strong className="font-semibold">Chapter progress</strong>
          <div className="my-2">
            <ProgressBar
              percent={(positionInChapter / activeGroupContent.length) * 100}
              label={`Chapter progress: section ${positionInChapter} of ${activeGroupContent.length}`}
              tone="sage"
            />
          </div>
          <span className="text-muted-foreground">
            Section {positionInChapter} of {activeGroupContent.length}
            {activeGroup ? ` · ${activeGroup.displayLabel}` : ""}
          </span>
        </div>
      )}
    </nav>
  );
}
