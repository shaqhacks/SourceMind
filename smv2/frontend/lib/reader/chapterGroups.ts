/**
 * Groups the reader's flat section list into chapters for sidebar display.
 * Reading order (order_index) is the single source of truth for navigation
 * (j/k/arrows in CourseReader) — this module only reshapes the same flat
 * list for presentation, it never reorders or filters what CourseReader
 * itself navigates through.
 */

import type { ReaderSection } from "./types";

export const FRONT_MATTER_LABEL = "Front matter";

/** Stable Set/DOM-id key for a group — distinct from the null label itself
 * so a real chapter that happened to be titled "Front matter" can never
 * collide with the null-label sentinel group. */
const FRONT_MATTER_KEY = "__front_matter__";

export interface ChapterGroup {
  /** Raw chapter_label, or null for front matter. */
  label: string | null;
  /** Stable, collision-safe identifier for React keys / aria-controls ids. */
  key: string;
  /** What to show the user — "Front matter" when label is null. */
  displayLabel: string;
  /** This chapter's sections, in reading order. */
  sections: ReaderSection[];
}

export function chapterGroupKey(label: string | null): string {
  return label ?? FRONT_MATTER_KEY;
}

/**
 * Groups sections by chapter_label, preserving reading order both within
 * and across groups — group boundaries fall wherever chapter_label changes
 * along that same order_index sequence, never a separate alphabetical or
 * other re-sort. A section with no chapter_label (`undefined`/`null`, the
 * latter until the backend field lands for real) groups under "Front
 * matter", forced to the very first position regardless of where it
 * appears in order_index (front matter is definitionally first — this is
 * just a defensive guard against a stray null-label section elsewhere).
 */
export function groupSectionsByChapter(sections: ReaderSection[]): ChapterGroup[] {
  const sorted = [...sections].sort((a, b) => a.order_index - b.order_index);
  const groups: ChapterGroup[] = [];
  const byKey = new Map<string, ChapterGroup>();

  for (const section of sorted) {
    const label = section.chapter_label ?? null;
    const key = chapterGroupKey(label);
    let group = byKey.get(key);
    if (!group) {
      group = { label, key, displayLabel: label ?? FRONT_MATTER_LABEL, sections: [] };
      byKey.set(key, group);
      groups.push(group);
    }
    group.sections.push(section);
  }

  const frontMatterIndex = groups.findIndex((group) => group.label === null);
  if (frontMatterIndex > 0) {
    const [frontMatter] = groups.splice(frontMatterIndex, 1);
    groups.unshift(frontMatter);
  }

  return groups;
}
