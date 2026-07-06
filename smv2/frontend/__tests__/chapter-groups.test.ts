import { describe, expect, it } from "vitest";

import { chapterGroupKey, FRONT_MATTER_LABEL, groupSectionsByChapter } from "@/lib/reader/chapterGroups";
import type { ReaderSection } from "@/lib/reader/types";

function makeSection(overrides: Partial<ReaderSection> = {}): ReaderSection {
  return {
    id: "sec-1",
    title: "Untitled",
    order_index: 0,
    page_start: 1,
    page_end: 5,
    lesson_status: "none",
    has_content: true,
    word_count: 100,
    kind: "content",
    chapter_label: null,
    ...overrides,
  };
}

describe("groupSectionsByChapter", () => {
  it("groups contiguous sections sharing a chapter_label, in reading order", () => {
    const sections = [
      makeSection({ id: "c1-content", order_index: 0, chapter_label: "Chapter 1" }),
      makeSection({ id: "c1-practice", order_index: 1, chapter_label: "Chapter 1", kind: "practice" }),
      makeSection({ id: "c1-answers", order_index: 2, chapter_label: "Chapter 1", kind: "answers" }),
      makeSection({ id: "c2-content", order_index: 3, chapter_label: "Chapter 2" }),
    ];

    const groups = groupSectionsByChapter(sections);

    expect(groups.map((g) => g.displayLabel)).toEqual(["Chapter 1", "Chapter 2"]);
    expect(groups[0].sections.map((s) => s.id)).toEqual(["c1-content", "c1-practice", "c1-answers"]);
    expect(groups[1].sections.map((s) => s.id)).toEqual(["c2-content"]);
  });

  it("sorts by order_index before grouping, regardless of input array order", () => {
    const sections = [
      makeSection({ id: "second", order_index: 1, chapter_label: "Chapter 1" }),
      makeSection({ id: "first", order_index: 0, chapter_label: "Chapter 1" }),
    ];

    const groups = groupSectionsByChapter(sections);

    expect(groups[0].sections.map((s) => s.id)).toEqual(["first", "second"]);
  });

  it("renders a null/undefined chapter_label as 'Front matter', forced to the first group", () => {
    const sections = [
      makeSection({ id: "chapter", order_index: 0, chapter_label: "Chapter 1" }),
      makeSection({ id: "front", order_index: 1, chapter_label: null }),
    ];

    const groups = groupSectionsByChapter(sections);

    expect(groups[0].displayLabel).toBe(FRONT_MATTER_LABEL);
    expect(groups[0].label).toBeNull();
    expect(groups[0].sections.map((s) => s.id)).toEqual(["front"]);
    expect(groups[1].displayLabel).toBe("Chapter 1");
  });

  it("treats a section with no chapter_label field at all the same as a null one", () => {
    const sections = [makeSection({ id: "sec-1" })]; // chapter_label omitted entirely
    const groups = groupSectionsByChapter(sections);

    expect(groups).toHaveLength(1);
    expect(groups[0].displayLabel).toBe(FRONT_MATTER_LABEL);
  });

  it("gives a real chapter literally titled 'Front matter' a distinct key from the null-label sentinel", () => {
    const sections = [
      makeSection({ id: "real-front-matter", order_index: 0, chapter_label: "Front matter" }),
      makeSection({ id: "null-label", order_index: 1, chapter_label: null }),
    ];

    const groups = groupSectionsByChapter(sections);
    const keys = groups.map((g) => g.key);

    expect(new Set(keys).size).toBe(2);
    expect(chapterGroupKey(null)).not.toBe(chapterGroupKey("Front matter"));
  });

  it("merges by label rather than by contiguous run, even if a label reappears non-contiguously", () => {
    // Not a realistic ingest output (chapter_label runs should always be
    // contiguous in order_index) — asserted explicitly since it's not
    // obvious from the happy-path case above that grouping is a map keyed
    // by label, not a "start a new group when the label changes" scan.
    const sections = [
      makeSection({ id: "a", order_index: 0, chapter_label: "Chapter 1" }),
      makeSection({ id: "b", order_index: 1, chapter_label: "Chapter 2" }),
      makeSection({ id: "c", order_index: 2, chapter_label: "Chapter 1" }),
    ];

    const groups = groupSectionsByChapter(sections);

    expect(groups.map((g) => g.displayLabel)).toEqual(["Chapter 1", "Chapter 2"]);
    expect(groups[0].sections.map((s) => s.id)).toEqual(["a", "c"]);
  });

  it("returns an empty array for an empty section list", () => {
    expect(groupSectionsByChapter([])).toEqual([]);
  });
});
