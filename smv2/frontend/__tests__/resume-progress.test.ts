import { describe, expect, it } from "vitest";

import { resolveResumeSectionId } from "@/lib/reader/resumeProgress";
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

describe("resolveResumeSectionId", () => {
  it("passes through null unchanged (no progress saved yet)", () => {
    const sections = [makeSection()];
    expect(resolveResumeSectionId(sections, null)).toBeNull();
  });

  it("passes through a content section's id unchanged", () => {
    const sections = [makeSection({ id: "sec-1" }), makeSection({ id: "sec-2", order_index: 1 })];
    expect(resolveResumeSectionId(sections, "sec-2")).toBe("sec-2");
  });

  it("passes through an id that doesn't exist in the section list at all", () => {
    const sections = [makeSection({ id: "sec-1" })];
    expect(resolveResumeSectionId(sections, "sec-deleted")).toBe("sec-deleted");
  });

  it("redirects a practice section forward to the next content section", () => {
    const sections = [
      makeSection({ id: "content-1", order_index: 0 }),
      makeSection({ id: "practice-1", order_index: 1, kind: "practice" }),
      makeSection({ id: "content-2", order_index: 2 }),
    ];
    expect(resolveResumeSectionId(sections, "practice-1")).toBe("content-2");
  });

  it("falls back to the previous content section when nothing follows", () => {
    const sections = [
      makeSection({ id: "content-1", order_index: 0 }),
      makeSection({ id: "practice-1", order_index: 1, kind: "practice" }),
      makeSection({ id: "answers-1", order_index: 2, kind: "answers" }),
    ];
    expect(resolveResumeSectionId(sections, "answers-1")).toBe("content-1");
  });

  it("prefers forward over backward when both exist", () => {
    const sections = [
      makeSection({ id: "content-before", order_index: 0 }),
      makeSection({ id: "practice-1", order_index: 1, kind: "practice" }),
      makeSection({ id: "content-after", order_index: 2 }),
    ];
    expect(resolveResumeSectionId(sections, "practice-1")).toBe("content-after");
  });

  it("returns the input unchanged when there is no content section anywhere", () => {
    const sections = [
      makeSection({ id: "practice-1", order_index: 0, kind: "practice" }),
      makeSection({ id: "answers-1", order_index: 1, kind: "answers" }),
    ];
    expect(resolveResumeSectionId(sections, "practice-1")).toBe("practice-1");
  });

  it("is not confused by input array order — sorts by order_index first", () => {
    const sections = [
      makeSection({ id: "content-2", order_index: 2 }),
      makeSection({ id: "practice-1", order_index: 1, kind: "practice" }),
      makeSection({ id: "content-1", order_index: 0 }),
    ];
    expect(resolveResumeSectionId(sections, "practice-1")).toBe("content-2");
  });
});
