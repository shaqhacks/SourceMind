import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CommandPalette from "@/components/search/CommandPalette";
import { searchCourse } from "@/lib/api/client";

let mockPathname = "/";
const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/lib/api/client", () => ({
  searchCourse: vi.fn(),
}));

const mockedSearchCourse = vi.mocked(searchCourse);

function ok<T>(data: T) {
  return { status: 200, ok: true, data };
}

describe("CommandPalette", () => {
  beforeEach(() => {
    mockPathname = "/";
    mockedSearchCourse.mockResolvedValue(
      ok({
        backend: "fts5",
        next_cursor: null,
        sanitized_excerpts: true,
        items: [
          {
            doc_type: "section",
            course_id: "course-1",
            section_id: "sec-1",
            asset_id: null,
            title: "Cell membranes",
            excerpt_md: "membrane result",
            source_locator: { page: 3, heading: "Membrane Basics", chapter: null, slide: null },
            score: 1,
            cursor_token: "cursor-1",
          },
        ],
      }),
    );
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("opens with Ctrl+K or Meta+K", async () => {
    render(<CommandPalette />);

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    fireEvent.keyDown(window, { key: "k", metaKey: true });
    expect(await screen.findByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
  });

  it("closes on Escape, outside pointer down, and restores focus", async () => {
    render(<CommandPalette />);
    const trigger = screen.getByRole("button", { name: "Open command palette" });
    trigger.focus();

    await userEvent.click(trigger);
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Command palette" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await userEvent.click(trigger);
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("dialog", { name: "Command palette" })).not.toBeInTheDocument();
  });

  it.each([
    ["Home", "/"],
    ["Review", "/review"],
    ["Flashcards", "/flashcards"],
    ["Tests", "/tests"],
    ["Jobs", "/jobs"],
    ["Settings", "/settings"],
    ["Search", "/search"],
  ])("runs the %s navigation action", async (label, href) => {
    const user = userEvent.setup();
    render(<CommandPalette />);

    await user.click(screen.getByRole("button", { name: "Open command palette" }));
    await user.click(screen.getByRole("button", { name: label }));

    expect(mockPush).toHaveBeenCalledWith(href);
  });

  it("searches only within the active course when present", async () => {
    const user = userEvent.setup();
    mockPathname = "/course/course-1";
    render(<CommandPalette />);

    await user.click(screen.getByRole("button", { name: "Open command palette" }));
    await user.type(screen.getByRole("searchbox", { name: "Search commands and active course" }), "membrane");

    await waitFor(() => {
      expect(mockedSearchCourse).toHaveBeenCalledWith("course-1", "membrane", { limit: 5 });
    });
    expect(await screen.findByRole("button", { name: "Open Cell membranes" })).toBeInTheDocument();
  });

  it("does not call course search when there is no active course", async () => {
    const user = userEvent.setup();
    render(<CommandPalette />);

    await user.click(screen.getByRole("button", { name: "Open command palette" }));
    await user.type(screen.getByRole("searchbox", { name: "Search commands and active course" }), "membrane");

    expect(mockedSearchCourse).not.toHaveBeenCalled();
    expect(screen.getByText(/open the Search page to choose a course/i)).toBeInTheDocument();
  });

  it("closes when the route changes", async () => {
    const { rerender } = render(<CommandPalette />);
    await userEvent.click(screen.getByRole("button", { name: "Open command palette" }));

    mockPathname = "/settings";
    rerender(<CommandPalette />);

    expect(screen.queryByRole("dialog", { name: "Command palette" })).not.toBeInTheDocument();
  });
});
