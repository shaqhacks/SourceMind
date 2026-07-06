import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { getDocument } from "pdfjs-dist";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CourseReader from "@/components/reader/CourseReader";
import {
  editOutline,
  findActiveCardsJob,
  findActiveLessonJob,
  getLessonEstimate,
  getLlmUsage,
  getSection,
  listCards,
  listChapters,
  listSections,
  saveProgress,
} from "@/lib/api/client";
import type { ReaderCourse, ReaderProgress } from "@/lib/reader/types";

import { err, ok } from "./support/api-result";
import { makeFakeDocument, makeFakePage } from "./support/fake-pdfjs";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
  getSection: vi.fn(),
  saveProgress: vi.fn(),
  getLessonEstimate: vi.fn(),
  findActiveLessonJob: vi.fn(),
  generateLesson: vi.fn(),
  getLlmUsage: vi.fn(),
  getChatHistory: vi.fn(),
  sendChat: vi.fn(),
  listCards: vi.fn(),
  findActiveCardsJob: vi.fn(),
  generateCards: vi.fn(),
  listSections: vi.fn(),
  editOutline: vi.fn(),
  listChapters: vi.fn(),
  buildAssetFileUrl: vi.fn((assetId: string) => `https://mock/api/assets/${assetId}/file`),
}));

// The reader tree imports PdfPagesView, which imports pdfjs-dist at
// module scope — jsdom has neither DOMMatrix nor Worker (see
// PdfPagesView.tsx's own guard for the latter), so the real module
// throws the moment it's evaluated.
vi.mock("pdfjs-dist", () => ({
  GlobalWorkerOptions: { workerPort: null },
  getDocument: vi.fn(),
}));

const mockedGetSection = vi.mocked(getSection);
const mockedSaveProgress = vi.mocked(saveProgress);
const mockedGetLessonEstimate = vi.mocked(getLessonEstimate);
const mockedFindActiveLessonJob = vi.mocked(findActiveLessonJob);
const mockedGetLlmUsage = vi.mocked(getLlmUsage);
const mockedListCards = vi.mocked(listCards);
const mockedFindActiveCardsJob = vi.mocked(findActiveCardsJob);
const mockedListSections = vi.mocked(listSections);
const mockedEditOutline = vi.mocked(editOutline);
const mockedListChapters = vi.mocked(listChapters);
const mockedGetDocument = vi.mocked(getDocument);

// A minimal 3-section fixture keeps these assertions about
// active-chapter bookkeeping (not content) easy to follow.
const COURSE: ReaderCourse = {
  id: "course-1",
  title: "Test Course",
  sections: [
    {
      id: "sec-1",
      title: "Chapter One",
      order_index: 0,
      page_start: 1,
      page_end: 5,
      lesson_status: "none",
      has_content: true,
      word_count: 100,
      kind: "content",
      chapter_label: null,
      asset_id: null,
    },
    {
      id: "sec-2",
      title: "Chapter Two",
      order_index: 1,
      page_start: 6,
      page_end: 10,
      lesson_status: "none",
      has_content: true,
      word_count: 120,
      kind: "content",
      chapter_label: null,
      asset_id: null,
    },
    {
      id: "sec-3",
      title: "Chapter Three",
      order_index: 2,
      page_start: 11,
      page_end: 15,
      lesson_status: "none",
      has_content: true,
      word_count: 90,
      kind: "content",
      chapter_label: null,
      asset_id: null,
    },
  ],
};

const BODIES: Record<string, string> = {
  "sec-1": "# Chapter One\n\nFirst body.",
  "sec-2": "# Chapter Two\n\nSecond body.",
  "sec-3": "# Chapter Three\n\nThird body.",
};

const NO_PROGRESS: ReaderProgress = { section_id: null, scroll_pos: 0 };

describe("CourseReader", () => {
  beforeEach(() => {
    mockedGetSection.mockImplementation((id: string) => {
      const section = COURSE.sections.find((candidate) => candidate.id === id);
      if (!section) return Promise.resolve(err(404));
      return Promise.resolve(
        ok({
          id: section.id,
          course_id: COURSE.id,
          title: section.title,
          order_index: section.order_index,
          page_start: section.page_start,
          page_end: section.page_end,
          kind: section.kind,
          chapter_label: section.chapter_label,
          asset_id: section.asset_id,
          body_md: BODIES[id],
          content_hash: "hash",
          lesson_md: null,
          lesson_status: section.lesson_status,
          lesson_stale: false,
          lesson_model: null,
          lesson_prompt_version: null,
          extractor_version: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        }),
      );
    });
    mockedSaveProgress.mockResolvedValue(
      ok({ course_id: COURSE.id, section_id: null, scroll_pos: 0, updated_at: null }),
    );
    mockedGetLessonEstimate.mockResolvedValue(
      ok({ est_seconds: 30, est_cost_usd: 0.01, based_on_calls: 0 }),
    );
    mockedFindActiveLessonJob.mockResolvedValue(null);
    mockedGetLlmUsage.mockResolvedValue(
      ok({ calls: 0, input_tokens: 0, output_tokens: 0, est_cost_usd: 0 }),
    );
    mockedListCards.mockResolvedValue(ok([]));
    mockedFindActiveCardsJob.mockResolvedValue(null);
    mockedListSections.mockResolvedValue(ok(COURSE.sections));
    mockedEditOutline.mockResolvedValue(ok(COURSE.sections));
    mockedListChapters.mockResolvedValue(ok([]));
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.useRealTimers();
    window.location.hash = "";
    // useReaderView (view-mode persistence) and useTypographyPrefs both
    // write to real localStorage (see vitest.setup.ts's polyfill, which
    // isn't reset automatically) — course-1 is reused across nearly every
    // test in this file, so a mode change in one test (e.g. "toggles
    // between source and lesson view with 's'") would otherwise leak into
    // every later test's initial render.
    window.localStorage.clear();
  });

  it("starts on the first chapter with focus on its heading", async () => {
    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);

    expect(screen.getByRole("button", { name: /chapter one/i })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByRole("heading", { level: 2, name: /chapter one/i })).toHaveFocus();

    await screen.findByText(/first body/i);
  });

  it("moves to the next chapter on ArrowRight and focuses its heading", async () => {
    const user = userEvent.setup();
    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    await screen.findByText(/first body/i);

    await user.keyboard("{ArrowRight}");

    expect(screen.getByRole("button", { name: /chapter two/i })).toHaveAttribute(
      "aria-current",
      "true",
    );
    expect(screen.getByRole("heading", { level: 2, name: /chapter two/i })).toHaveFocus();
  });

  it("moves forward with 'j' and back with 'k'", async () => {
    const user = userEvent.setup();
    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    await screen.findByText(/first body/i);

    await user.keyboard("j");
    await user.keyboard("j");
    expect(screen.getByRole("button", { name: /chapter three/i })).toHaveAttribute(
      "aria-current",
      "true",
    );

    await user.keyboard("k");
    expect(screen.getByRole("button", { name: /chapter two/i })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("clamps at the first and last chapters instead of wrapping", async () => {
    const user = userEvent.setup();
    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    await screen.findByText(/first body/i);

    await user.keyboard("k"); // already first chapter — no-op
    expect(screen.getByRole("button", { name: /chapter one/i })).toHaveAttribute(
      "aria-current",
      "true",
    );

    await user.keyboard("{ArrowRight}{ArrowRight}{ArrowRight}"); // only 2 hops available
    expect(screen.getByRole("button", { name: /chapter three/i })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("selecting a chapter from the sidebar makes it active and focuses its heading", async () => {
    const user = userEvent.setup();
    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    await screen.findByText(/first body/i);

    await user.click(screen.getByRole("button", { name: /chapter three/i }));

    expect(screen.getByRole("heading", { level: 2, name: /chapter three/i })).toHaveFocus();
  });

  it("opens the shortcuts overlay with '?' and suppresses chapter navigation while it's open", async () => {
    const user = userEvent.setup();
    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    await screen.findByText(/first body/i);

    await user.keyboard("?");
    expect(screen.getByRole("dialog", { name: /keyboard shortcuts/i })).toBeInTheDocument();

    // The overlay's own "escape" scope sits on top of the reader's
    // shortcut scope while open, so arrow/j/k must not navigate chapters.
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("button", { name: /chapter one/i })).toHaveAttribute(
      "aria-current",
      "true",
    );

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("toggles between source and lesson view with 's'", async () => {
    const user = userEvent.setup();
    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);

    // Wait for the lazy body fetch to resolve first — its own "Loading
    // chapter…" state uses role="status" too, which would otherwise
    // collide with the "not in the document yet" assertion below.
    await screen.findByText(/first body/i);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    await user.keyboard("s");

    // lesson_status "none" (never generated) renders the CTA card.
    expect(await screen.findByRole("button", { name: /generate lesson/i })).toBeInTheDocument();
  });

  it("applies typography prefs to the reading column as CSS custom properties, live", async () => {
    const user = userEvent.setup();
    render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
    await screen.findByText(/first body/i);

    const column = screen.getByTestId("reading-column");
    // Defaults from useTypographyPrefs, applied with no user interaction.
    expect(column.style.getPropertyValue("--reading-font-size")).toBe("18px");
    expect(column.style.getPropertyValue("--reading-measure")).toBe("70ch");
    expect(column.style.getPropertyValue("--reading-line-height")).toBe("1.6");

    await user.click(screen.getByRole("button", { name: /typography settings/i }));
    fireEvent.change(screen.getByRole("slider", { name: /font size/i }), {
      target: { value: "22" },
    });

    // TypographyControls and ReadingColumn share the same
    // useSyncExternalStore-backed store, so the change is reflected
    // without any prop drilling or remount.
    expect(column.style.getPropertyValue("--reading-font-size")).toBe("22px");
  });

  describe("resume", () => {
    it("starts on the saved section instead of the first one", async () => {
      render(
        <CourseReader
          course={COURSE}
          initialProgress={{ section_id: "sec-2", scroll_pos: 0 }}
        />,
      );

      expect(screen.getByRole("button", { name: /chapter two/i })).toHaveAttribute(
        "aria-current",
        "true",
      );
      await screen.findByText(/second body/i);
    });

    it("falls back to the first chapter when the saved section no longer exists", async () => {
      render(
        <CourseReader
          course={COURSE}
          initialProgress={{ section_id: "sec-deleted", scroll_pos: 0.5 }}
        />,
      );

      expect(screen.getByRole("button", { name: /chapter one/i })).toHaveAttribute(
        "aria-current",
        "true",
      );
    });

    it("jumps to the saved scroll position once the resumed chapter's body has loaded, without animating", async () => {
      render(
        <CourseReader
          course={COURSE}
          initialProgress={{ section_id: "sec-2", scroll_pos: 0.6 }}
        />,
      );

      const column = screen.getByTestId("reading-column");
      Object.defineProperty(column, "scrollHeight", { value: 1000, configurable: true });
      Object.defineProperty(column, "clientHeight", { value: 500, configurable: true });

      await screen.findByText(/second body/i);

      // scrollable = 1000 - 500 = 500; 60% of that = 300.
      expect(column.scrollTop).toBe(300);
    });
  });

  describe("hash deep-links", () => {
    it("scrolls a heading matching location.hash into view once the body renders, taking priority over the saved scroll position", async () => {
      window.location.hash = "#chapter-two";
      const scrollIntoViewSpy = vi.spyOn(HTMLElement.prototype, "scrollIntoView");

      render(
        <CourseReader
          course={COURSE}
          initialProgress={{ section_id: "sec-2", scroll_pos: 0.6 }}
        />,
      );

      await screen.findByText(/second body/i);

      const heading = screen.getByRole("heading", { name: /chapter two/i, level: 1 });
      expect(heading).toHaveAttribute("id", "chapter-two");
      expect(scrollIntoViewSpy).toHaveBeenCalledWith(
        expect.objectContaining({ block: "start" }),
      );
      expect(scrollIntoViewSpy.mock.instances[0]).toBe(heading);
    });

    it("scrolls to a heading when the hash changes via an in-page anchor click", async () => {
      render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
      await screen.findByText(/first body/i);

      const scrollIntoViewSpy = vi.spyOn(HTMLElement.prototype, "scrollIntoView");
      window.location.hash = "#chapter-one";
      act(() => {
        window.dispatchEvent(new Event("hashchange"));
      });

      const heading = screen.getByRole("heading", { name: /chapter one/i, level: 1 });
      expect(scrollIntoViewSpy).toHaveBeenCalled();
      expect(scrollIntoViewSpy.mock.instances[0]).toBe(heading);
    });
  });

  describe("progress sync", () => {
    it("does not re-save progress for the section it resumed into on mount", async () => {
      render(
        <CourseReader
          course={COURSE}
          initialProgress={{ section_id: "sec-2", scroll_pos: 0.6 }}
        />,
      );
      await screen.findByText(/second body/i);

      expect(mockedSaveProgress).not.toHaveBeenCalled();
    });

    it("saves progress immediately (scroll_pos 0) when the active chapter changes", async () => {
      const user = userEvent.setup();
      render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
      await screen.findByText(/first body/i);

      await user.keyboard("{ArrowRight}");

      expect(mockedSaveProgress).toHaveBeenCalledWith("course-1", {
        section_id: "sec-2",
        scroll_pos: 0,
      });
    });

    it("saves progress on scroll, debounced by about a second", async () => {
      vi.useFakeTimers();

      await act(async () => {
        render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
      });

      const column = screen.getByTestId("reading-column");
      Object.defineProperty(column, "scrollHeight", { value: 1000, configurable: true });
      Object.defineProperty(column, "clientHeight", { value: 500, configurable: true });
      column.scrollTop = 250;

      act(() => {
        fireEvent.scroll(column);
      });

      act(() => {
        vi.advanceTimersByTime(999);
      });
      expect(mockedSaveProgress).not.toHaveBeenCalled();

      act(() => {
        vi.advanceTimersByTime(1);
      });
      expect(mockedSaveProgress).toHaveBeenCalledWith("course-1", {
        section_id: "sec-1",
        scroll_pos: 0.5,
      });
    });
  });

  describe("outline editor", () => {
    it("opens via the TopBar 'Edit outline' button", async () => {
      const user = userEvent.setup();
      render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
      await screen.findByText(/first body/i);

      await user.click(screen.getByRole("button", { name: /edit outline/i }));

      expect(await screen.findByRole("dialog", { name: /edit outline/i })).toBeInTheDocument();
      expect(mockedListSections).toHaveBeenCalledWith("course-1");
    });

    it("opens via the 'o' shortcut and suppresses chapter navigation underneath while open", async () => {
      const user = userEvent.setup();
      render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
      await screen.findByText(/first body/i);

      await user.keyboard("o");
      expect(await screen.findByRole("dialog", { name: /edit outline/i })).toBeInTheDocument();

      await user.keyboard("{ArrowRight}");
      // Scoped to the sidebar nav: the outline editor's own "Chapter One"
      // rename-trigger button, once its data loads, shares this same
      // accessible name.
      const sidebar = screen.getByRole("navigation", { name: /chapter outline/i });
      expect(within(sidebar).getByRole("button", { name: /chapter one/i })).toHaveAttribute(
        "aria-current",
        "true",
      );
    });

    it("closes on Escape and restores focus to the triggering button", async () => {
      const user = userEvent.setup();
      render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
      await screen.findByText(/first body/i);

      const trigger = screen.getByRole("button", { name: /edit outline/i });
      await user.click(trigger);
      await screen.findByRole("dialog", { name: /edit outline/i });

      await user.keyboard("{Escape}");

      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      expect(document.activeElement).toBe(trigger);
    });

    it("renaming a chapter and saving issues one edit_outline PATCH and refreshes the sidebar", async () => {
      const user = userEvent.setup();
      render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
      await screen.findByText(/first body/i);

      await user.click(screen.getByRole("button", { name: /edit outline/i }));
      const dialog = await screen.findByRole("dialog", { name: /edit outline/i });

      mockedEditOutline.mockResolvedValue(
        ok(
          COURSE.sections.map((section) =>
            section.id === "sec-1" ? { ...section, title: "Renamed Chapter" } : section,
          ),
        ),
      );

      await user.click(await within(dialog).findByRole("button", { name: "Chapter One" }));
      const input = within(dialog).getByRole("textbox", { name: /rename chapter one/i });
      await user.clear(input);
      await user.type(input, "Renamed Chapter{Enter}");

      await user.click(within(dialog).getByRole("button", { name: /save changes/i }));

      expect(mockedEditOutline).toHaveBeenCalledWith("course-1", [
        { type: "rename", section_id: "sec-1", title: "Renamed Chapter" },
      ]);
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      // A sidebar row's accessible name is a concatenation of the lesson
      // dot's own aria-label, the title, and the page range (see Sidebar.tsx)
      // — never an exact match, hence the regex (same as every other
      // sidebar-button query in this file).
      const sidebar = screen.getByRole("navigation", { name: /chapter outline/i });
      expect(
        await within(sidebar).findByRole("button", { name: /renamed chapter/i }),
      ).toBeInTheDocument();
    });
  });

  describe("non-content sections (practice/answers)", () => {
    // A practice section sits between two content chapters — keyboard nav
    // must step over it entirely, same as it's excluded from Sidebar's
    // reading list (see sidebar-chapter-groups.test.tsx).
    const COURSE_WITH_PRACTICE: ReaderCourse = {
      id: "course-1",
      title: "Test Course",
      sections: [
        {
          id: "sec-1",
          title: "Chapter One",
          order_index: 0,
          page_start: 1,
          page_end: 5,
          lesson_status: "none",
          has_content: true,
          word_count: 100,
          kind: "content",
          chapter_label: "Chapter 1",
          asset_id: null,
        },
        {
          id: "sec-practice",
          title: "Practice Set",
          order_index: 1,
          page_start: 6,
          page_end: 6,
          lesson_status: "none",
          has_content: true,
          word_count: 20,
          kind: "practice",
          chapter_label: "Chapter 1",
          asset_id: null,
        },
        {
          id: "sec-2",
          title: "Chapter Two",
          order_index: 2,
          page_start: 7,
          page_end: 10,
          lesson_status: "none",
          has_content: true,
          word_count: 120,
          kind: "content",
          chapter_label: "Chapter 2",
          asset_id: null,
        },
      ],
    };

    const PRACTICE_BODIES: Record<string, string> = {
      "sec-1": "# Chapter One\n\nFirst body.",
      "sec-practice": "Practice: solve for x.",
      "sec-2": "# Chapter Two\n\nSecond body.",
    };

    function mockGetSectionForCourse(course: ReaderCourse, bodies: Record<string, string>) {
      mockedGetSection.mockImplementation((id: string) => {
        const section = course.sections.find((candidate) => candidate.id === id);
        if (!section) return Promise.resolve(err(404));
        return Promise.resolve(
          ok({
            id: section.id,
            course_id: course.id,
            title: section.title,
            order_index: section.order_index,
            page_start: section.page_start,
            page_end: section.page_end,
            kind: section.kind,
            chapter_label: section.chapter_label,
            asset_id: section.asset_id,
            body_md: bodies[id],
            content_hash: "hash",
            lesson_md: null,
            lesson_status: section.lesson_status,
            lesson_stale: false,
            lesson_model: null,
            lesson_prompt_version: null,
            extractor_version: null,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          }),
        );
      });
    }

    it("skips a practice section moving forward with ArrowRight/j", async () => {
      mockGetSectionForCourse(COURSE_WITH_PRACTICE, PRACTICE_BODIES);
      const user = userEvent.setup();
      render(<CourseReader course={COURSE_WITH_PRACTICE} initialProgress={NO_PROGRESS} />);
      await screen.findByText(/first body/i);

      await user.keyboard("{ArrowRight}");

      expect(screen.getByRole("heading", { level: 2, name: /chapter two/i })).toHaveFocus();
      await screen.findByText(/second body/i);
    });

    it("skips a practice section moving backward with ArrowLeft/k", async () => {
      mockGetSectionForCourse(COURSE_WITH_PRACTICE, PRACTICE_BODIES);
      const user = userEvent.setup();
      render(
        <CourseReader
          course={COURSE_WITH_PRACTICE}
          initialProgress={{ section_id: "sec-2", scroll_pos: 0 }}
        />,
      );
      await screen.findByText(/second body/i);

      await user.keyboard("{ArrowLeft}");

      expect(screen.getByRole("heading", { level: 2, name: /chapter one/i })).toHaveFocus();
      await screen.findByText(/first body/i);
    });

    it("does not move at all when only a non-content section lies in the requested direction", async () => {
      const TRAILING_PRACTICE: ReaderCourse = {
        ...COURSE_WITH_PRACTICE,
        sections: [
          COURSE_WITH_PRACTICE.sections[0],
          COURSE_WITH_PRACTICE.sections[2],
          { ...COURSE_WITH_PRACTICE.sections[1], order_index: 2 },
        ],
      };
      mockGetSectionForCourse(TRAILING_PRACTICE, PRACTICE_BODIES);
      const user = userEvent.setup();
      render(
        <CourseReader
          course={TRAILING_PRACTICE}
          initialProgress={{ section_id: "sec-2", scroll_pos: 0 }}
        />,
      );
      await screen.findByText(/second body/i);

      await user.keyboard("{ArrowRight}"); // only a trailing practice section follows

      // Still on Chapter Two — no content section to advance into.
      expect(screen.getByRole("heading", { level: 2, name: /chapter two/i })).toHaveFocus();
    });

    it("shows a banner with a link to the chapter test when a non-content section is reached directly", async () => {
      mockGetSectionForCourse(COURSE_WITH_PRACTICE, PRACTICE_BODIES);
      render(
        <CourseReader
          course={COURSE_WITH_PRACTICE}
          initialProgress={{ section_id: "sec-practice", scroll_pos: 0 }}
        />,
      );

      expect(await screen.findByText(/practice: solve for x/i)).toBeInTheDocument();
      expect(screen.getByRole("note", { name: /reading flow notice/i })).toHaveTextContent(
        /practice material/i,
      );
      expect(screen.getByRole("link", { name: /go to chapter test/i })).toHaveAttribute(
        "href",
        "/course/course-1/chapter/Chapter%201/test",
      );
    });

    it("shows no banner on an ordinary content section", async () => {
      mockGetSectionForCourse(COURSE_WITH_PRACTICE, PRACTICE_BODIES);
      render(<CourseReader course={COURSE_WITH_PRACTICE} initialProgress={NO_PROGRESS} />);
      await screen.findByText(/first body/i);

      expect(screen.queryByRole("note", { name: /reading flow notice/i })).not.toBeInTheDocument();
    });
  });

  describe("view toggle (source / pages / lesson)", () => {
    const COURSE_WITH_ASSET: ReaderCourse = {
      id: "course-asset",
      title: "Test Course",
      sections: [
        {
          id: "sec-asset",
          title: "Chapter One",
          order_index: 0,
          page_start: 1,
          page_end: 2,
          lesson_status: "none",
          has_content: true,
          word_count: 100,
          kind: "content",
          chapter_label: "Chapter 1",
          asset_id: "asset-1",
        },
      ],
    };

    beforeEach(() => {
      mockedGetSection.mockImplementation((id: string) => {
        // Some of this block's own tests render the plain COURSE fixture
        // (no asset_id, to exercise the "Pages disabled" state) rather
        // than COURSE_WITH_ASSET — fall back to it here rather than only
        // knowing about "sec-asset", or COURSE's own sections 404.
        const plainSection = COURSE.sections.find((section) => section.id === id);
        if (plainSection) {
          return Promise.resolve(
            ok({
              id: plainSection.id,
              course_id: COURSE.id,
              title: plainSection.title,
              order_index: plainSection.order_index,
              page_start: plainSection.page_start,
              page_end: plainSection.page_end,
              kind: plainSection.kind,
              chapter_label: plainSection.chapter_label,
              asset_id: plainSection.asset_id,
              body_md: BODIES[id],
              content_hash: "hash",
              lesson_md: null,
              lesson_status: plainSection.lesson_status,
              lesson_stale: false,
              lesson_model: null,
              lesson_prompt_version: null,
              extractor_version: null,
              created_at: "2026-01-01T00:00:00Z",
              updated_at: "2026-01-01T00:00:00Z",
            }),
          );
        }
        if (id !== "sec-asset") return Promise.resolve(err(404));
        return Promise.resolve(
          ok({
            id: "sec-asset",
            course_id: "course-asset",
            title: "Chapter One",
            order_index: 0,
            page_start: 1,
            page_end: 2,
            kind: "content" as const,
            chapter_label: "Chapter 1",
            asset_id: "asset-1",
            body_md: "# Chapter One\n\nSource body.",
            content_hash: "hash",
            lesson_md: null,
            lesson_status: "none" as const,
            lesson_stale: false,
            lesson_model: null,
            lesson_prompt_version: null,
            extractor_version: null,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          }),
        );
      });
    });

    it("disables the Pages option (with a tooltip) when the active section has no asset_id", async () => {
      render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
      await screen.findByText(/first body/i);

      const pagesButton = screen.getByRole("button", { name: "Pages" });
      expect(pagesButton).toBeDisabled();
      expect(pagesButton).toHaveAttribute("title", "Re-ingest this course to enable original pages");
    });

    it("cycling with 's' skips the disabled Pages option, going straight from source to lesson", async () => {
      const user = userEvent.setup();
      render(<CourseReader course={COURSE} initialProgress={NO_PROGRESS} />);
      await screen.findByText(/first body/i);

      await user.keyboard("s");

      expect(await screen.findByRole("button", { name: /generate lesson/i })).toBeInTheDocument();
    });

    it("clicking Pages switches to the original-PDF view and renders its pages", async () => {
      const doc = makeFakeDocument({ 1: makeFakePage(), 2: makeFakePage() });
      mockedGetDocument.mockReturnValue({
        promise: Promise.resolve(doc),
      } as unknown as ReturnType<typeof getDocument>);

      const user = userEvent.setup();
      render(<CourseReader course={COURSE_WITH_ASSET} initialProgress={NO_PROGRESS} />);
      await screen.findByText(/source body/i);

      await user.click(screen.getByRole("button", { name: "Pages" }));

      // jsdom has no IntersectionObserver at all, so PdfPagesView's own
      // fail-open guard renders every page's canvas immediately rather
      // than gating on a (nonexistent) intersection signal — the lazy
      // near-viewport-only behavior itself is covered by
      // pdf-pages-view.test.tsx, which stubs a fake observer.
      expect(await screen.findByLabelText("Page 1")).toBeInTheDocument();
      expect(screen.getByLabelText("Page 2")).toBeInTheDocument();
      expect(mockedGetDocument).toHaveBeenCalledWith({
        url: "https://mock/api/assets/asset-1/file",
      });
    });

    it("persists the chosen view per course — a remount honors the last choice", async () => {
      const doc = makeFakeDocument({ 1: makeFakePage(), 2: makeFakePage() });
      mockedGetDocument.mockReturnValue({
        promise: Promise.resolve(doc),
      } as unknown as ReturnType<typeof getDocument>);

      const user = userEvent.setup();
      const { unmount } = render(
        <CourseReader course={COURSE_WITH_ASSET} initialProgress={NO_PROGRESS} />,
      );
      await screen.findByText(/source body/i);
      await user.click(screen.getByRole("button", { name: "Pages" }));
      await screen.findByLabelText("Page 1");
      unmount();

      render(<CourseReader course={COURSE_WITH_ASSET} initialProgress={NO_PROGRESS} />);

      expect(await screen.findByLabelText("Page 1")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Pages" })).toHaveAttribute("aria-pressed", "true");
    });
  });
});
