import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import Sidebar from "@/components/reader/Sidebar";
import type { ReaderSection } from "@/lib/reader/types";

function makeSection(overrides: Partial<ReaderSection> = {}): ReaderSection {
  return {
    id: "sec-1",
    title: "Introduction",
    order_index: 0,
    page_start: 1,
    page_end: 5,
    lesson_status: "none",
    has_content: true,
    word_count: 100,
    kind: "content",
    chapter_label: null,
    asset_id: null,
    ...overrides,
  };
}

describe("Sidebar lesson status dots", () => {
  afterEach(() => {
    cleanup();
  });

  it("labels a dot from the section's own lesson_status", () => {
    render(
      <Sidebar
        courseId="course-1"
        sections={[makeSection({ lesson_status: "ready" })]}
        activeSectionId="sec-1"
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Lesson ready")).toBeInTheDocument();
  });

  it("prefers a lessonStatusOverrides entry over the section's own lesson_status", () => {
    render(
      <Sidebar
        courseId="course-1"
        sections={[makeSection({ lesson_status: "none" })]}
        activeSectionId="sec-1"
        onSelect={vi.fn()}
        lessonStatusOverrides={{ "sec-1": "generating" }}
      />,
    );

    expect(screen.getByLabelText("Lesson generating")).toBeInTheDocument();
    expect(screen.queryByLabelText("No lesson yet")).not.toBeInTheDocument();
  });

  it("shows the synthetic stale label, which list_sections itself never carries", () => {
    render(
      <Sidebar
        courseId="course-1"
        sections={[makeSection({ lesson_status: "ready" })]}
        activeSectionId="sec-1"
        onSelect={vi.fn()}
        lessonStatusOverrides={{ "sec-1": "stale" }}
      />,
    );

    expect(screen.getByLabelText("Lesson needs regeneration")).toBeInTheDocument();
  });
});
