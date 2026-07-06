import type { ReaderSection } from "./types";

/**
 * Walks from `currentIndex` in `direction` (+1/-1) until landing on a
 * content section, skipping practice/answers along the way — their home
 * is the chapter test page, not the reading flow (see chapterGroups.ts).
 * Returns null if the walk runs off either end without finding one, the
 * same "clamp instead of landing off-flow" semantics CourseReader's own
 * keyboard nav uses. Shared by CourseReader's goToOffset (the mutation)
 * and the reading column's prev/next chevrons (the "is there a target at
 * all" visibility check) so the two can never disagree about what's
 * reachable.
 */
export function findNextContentIndex(
  sections: ReaderSection[],
  currentIndex: number,
  direction: 1 | -1,
): number | null {
  let candidate = currentIndex;
  for (;;) {
    candidate += direction;
    if (candidate < 0 || candidate > sections.length - 1) return null;
    if (sections[candidate].kind === "content") return candidate;
  }
}
