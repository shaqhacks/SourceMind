/**
 * A saved progress `section_id` might point at a section that's since been
 * excluded from the sidebar's reading list (practice/answers — see
 * chapterGroups.ts) and from keyboard nav (see CourseReader's goToOffset).
 * Resuming directly into one would land the reader on a section with no
 * sidebar row highlighted and no natural "next" implied — redirect to the
 * nearest content section instead: forward first (continue reading
 * onward), then backward if nothing follows.
 *
 * A `sectionId` that's null, already content-kind, or not found in
 * `sections` at all passes through unchanged — CourseReader's own
 * activeIndex resolution already falls back to the first section for a
 * truly missing id, and that's a different concern from this redirect.
 */

import type { ReaderSection } from "./types";

export function resolveResumeSectionId(
  sections: ReaderSection[],
  sectionId: string | null,
): string | null {
  if (!sectionId) return sectionId;

  const sorted = [...sections].sort((a, b) => a.order_index - b.order_index);
  const index = sorted.findIndex((section) => section.id === sectionId);
  if (index === -1) return sectionId;
  if (sorted[index].kind === "content") return sectionId;

  for (let i = index + 1; i < sorted.length; i += 1) {
    if (sorted[i].kind === "content") return sorted[i].id;
  }
  for (let i = index - 1; i >= 0; i -= 1) {
    if (sorted[i].kind === "content") return sorted[i].id;
  }
  return sectionId; // no content sections anywhere — nothing better to land on
}
