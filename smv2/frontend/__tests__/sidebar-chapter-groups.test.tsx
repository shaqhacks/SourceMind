import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import Sidebar from "@/components/reader/Sidebar";
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
    asset_id: null,
    ...overrides,
  };
}

// Two chapters, each with a content + practice + answers section, so
// grouping/chips/keyboard-order all have something real to assert against.
const SECTIONS: ReaderSection[] = [
  makeSection({ id: "c1-content", order_index: 0, title: "Foundations", chapter_label: "Chapter 1" }),
  makeSection({
    id: "c1-practice",
    order_index: 1,
    title: "Practice Set",
    chapter_label: "Chapter 1",
    kind: "practice",
  }),
  makeSection({
    id: "c1-answers",
    order_index: 2,
    title: "Answer Key",
    chapter_label: "Chapter 1",
    kind: "answers",
  }),
  makeSection({ id: "c2-content", order_index: 3, title: "Structures", chapter_label: "Chapter 2" }),
];

describe("Sidebar chapter grouping", () => {
  afterEach(() => {
    cleanup();
  });

  it("groups sections under their chapter_label, collapsed by default except the active section's group", () => {
    render(
      <Sidebar
        courseId="course-1"
        sections={SECTIONS}
        activeSectionId="c1-content"
        onSelect={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: /chapter 1/i })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("Foundations")).toBeInTheDocument();

    // Chapter 2 isn't active — collapsed, its row not in the document.
    expect(screen.getByRole("button", { name: /chapter 2/i })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByText("Structures")).not.toBeInTheDocument();
  });

  it("expands and collapses a non-active group on click, aria-expanded tracks it", async () => {
    const user = userEvent.setup();
    render(
      <Sidebar
        courseId="course-1"
        sections={SECTIONS}
        activeSectionId="c1-content"
        onSelect={vi.fn()}
      />,
    );

    const chapter2Toggle = screen.getByRole("button", { name: /chapter 2/i });
    expect(screen.queryByText("Structures")).not.toBeInTheDocument();

    await user.click(chapter2Toggle);
    expect(chapter2Toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Structures")).toBeInTheDocument();

    await user.click(chapter2Toggle);
    expect(chapter2Toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Structures")).not.toBeInTheDocument();
  });

  it("keeps the active group open — clicking its own toggle is a no-op", async () => {
    const user = userEvent.setup();
    render(
      <Sidebar
        courseId="course-1"
        sections={SECTIONS}
        activeSectionId="c1-content"
        onSelect={vi.fn()}
      />,
    );

    const chapter1Toggle = screen.getByRole("button", { name: /chapter 1/i });
    await user.click(chapter1Toggle);

    expect(chapter1Toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Foundations")).toBeInTheDocument();
  });

  it("aria-controls on the toggle matches the id of the group's own list", () => {
    render(
      <Sidebar
        courseId="course-1"
        sections={SECTIONS}
        activeSectionId="c1-content"
        onSelect={vi.fn()}
      />,
    );

    const toggle = screen.getByRole("button", { name: /chapter 1/i });
    const controlsId = toggle.getAttribute("aria-controls");
    expect(controlsId).toBeTruthy();
    expect(document.getElementById(controlsId!)).toContainElement(screen.getByText("Foundations"));
  });

  it("never lists practice/answers sections as reading rows, even in their expanded group", () => {
    render(
      <Sidebar
        courseId="course-1"
        sections={SECTIONS}
        activeSectionId="c1-content"
        onSelect={vi.fn()}
      />,
    );

    // Chapter 1's group is expanded (it's the active section's group) —
    // its content row is present, but practice/answers never render here;
    // their home is the chapter's "Test" link instead.
    expect(screen.getByText("Foundations")).toBeInTheDocument();
    expect(screen.queryByText("Practice Set")).not.toBeInTheDocument();
    expect(screen.queryByText("Answer Key")).not.toBeInTheDocument();
  });

  it("onSelect always receives the section's index in the flat (ungrouped) list, not a group-relative index", async () => {
    const user = userEvent.setup();
    const onSelect = vi.fn();
    render(
      <Sidebar
        courseId="course-1"
        sections={SECTIONS}
        activeSectionId="c1-content"
        onSelect={onSelect}
      />,
    );

    // "Structures" is index 3 in the flat SECTIONS array, but would be
    // index 0 within its own (Chapter 2) group — the bug this guards
    // against is passing the latter.
    await user.click(screen.getByRole("button", { name: /chapter 2/i }));
    await user.click(screen.getByText("Structures"));

    expect(onSelect).toHaveBeenCalledWith(3);
  });

  it("links each chapter group's 'Test' affordance to its own chapter test page, URL-encoding the label", () => {
    render(
      <Sidebar
        courseId="course-1"
        sections={SECTIONS}
        activeSectionId="c1-content"
        onSelect={vi.fn()}
      />,
    );

    // Chapter 1 has a practice section, so its label is "Test · N practice
    // sheet(s)" rather than bare "Test" (see the next test for that count)
    // — match on the "Test" prefix rather than an exact string.
    const testLinks = screen.getAllByRole("link", { name: /^test/i });
    expect(testLinks).toHaveLength(2);
    expect(testLinks[0]).toHaveAttribute("href", "/course/course-1/chapter/Chapter%201/test");
    expect(testLinks[1]).toHaveAttribute("href", "/course/course-1/chapter/Chapter%202/test");
  });

  it("shows the practice-sheet count on the Test link before any score exists", () => {
    render(
      <Sidebar
        courseId="course-1"
        sections={SECTIONS}
        activeSectionId="c1-content"
        onSelect={vi.fn()}
      />,
    );

    // Chapter 1 has one practice section and no test_stats yet.
    expect(screen.getByRole("link", { name: /test.*1 practice sheet/i })).toBeInTheDocument();
    // Chapter 2 has no practice sections at all — plain "Test".
    expect(screen.getByRole("link", { name: /^test$/i })).toBeInTheDocument();
  });

  it("shows the best score on the Test link once chapterStats is populated", () => {
    render(
      <Sidebar
        courseId="course-1"
        sections={SECTIONS}
        activeSectionId="c1-content"
        onSelect={vi.fn()}
        chapterStats={{ "Chapter 1": { attempts: 2, best_score: 0.75, latest_score: 0.5 } }}
      />,
    );

    expect(screen.getByRole("link", { name: /test.*75%/i })).toBeInTheDocument();
  });

  it("renders sections with no chapter_label under 'Front matter', with no Test affordance", () => {
    const sections = [
      makeSection({ id: "front", order_index: 0, title: "Title Page", chapter_label: null }),
      ...SECTIONS,
    ];
    render(
      <Sidebar courseId="course-1" sections={sections} activeSectionId="front" onSelect={vi.fn()} />,
    );

    expect(screen.getByRole("button", { name: /front matter/i })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
    expect(screen.getByText("Title Page")).toBeInTheDocument();
    // Only Chapter 1 and Chapter 2 get a Test link — front matter doesn't.
    expect(screen.getAllByRole("link", { name: /^test/i })).toHaveLength(2);
  });
});
