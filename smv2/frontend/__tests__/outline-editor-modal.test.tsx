import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import OutlineEditorModal from "@/components/reader/OutlineEditorModal";
import { editOutline, listSections, type SectionOut } from "@/lib/api/client";

import { err, ok } from "./support/api-result";

vi.mock("@/lib/api/client", () => ({
  listSections: vi.fn(),
  editOutline: vi.fn(),
}));

const mockedListSections = vi.mocked(listSections);
const mockedEditOutline = vi.mocked(editOutline);

function makeSection(overrides: Partial<SectionOut> = {}): SectionOut {
  return {
    id: "sec-1",
    title: "Chapter One",
    order_index: 0,
    page_start: 1,
    page_end: 10,
    lesson_status: "none",
    has_content: true,
    word_count: 100,
    kind: "content",
    chapter_label: null,
    ...overrides,
  };
}

describe("OutlineEditorModal", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders nothing and fetches nothing while closed", () => {
    render(
      <OutlineEditorModal courseId="course-1" open={false} onClose={vi.fn()} onApplied={vi.fn()} />,
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mockedListSections).not.toHaveBeenCalled();
  });

  it("loads the current outline via list_sections when opened", async () => {
    mockedListSections.mockResolvedValue(ok([makeSection()]));

    render(<OutlineEditorModal courseId="course-1" open onClose={vi.fn()} onApplied={vi.fn()} />);

    expect(mockedListSections).toHaveBeenCalledWith("course-1");
    expect(await screen.findByText("Chapter One")).toBeInTheDocument();
  });

  it("shows an error banner when list_sections fails, with no editor beneath it", async () => {
    mockedListSections.mockResolvedValue(err(500));

    render(<OutlineEditorModal courseId="course-1" open onClose={vi.fn()} onApplied={vi.fn()} />);

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /save changes/i })).not.toBeInTheDocument();
  });

  it("renaming a chapter and saving issues one edit_outline PATCH, then applies and closes", async () => {
    mockedListSections.mockResolvedValue(ok([makeSection()]));
    const renamed = [makeSection({ title: "Renamed" })];
    mockedEditOutline.mockResolvedValue(ok(renamed));
    const onApplied = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(<OutlineEditorModal courseId="course-1" open onClose={onClose} onApplied={onApplied} />);

    await user.click(await screen.findByRole("button", { name: "Chapter One" }));
    const input = screen.getByRole("textbox", { name: /rename chapter one/i });
    await user.clear(input);
    await user.type(input, "Renamed{Enter}");

    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() =>
      expect(mockedEditOutline).toHaveBeenCalledWith("course-1", [
        { type: "rename", section_id: "sec-1", title: "Renamed" },
      ]),
    );
    expect(onApplied).toHaveBeenCalledWith(renamed);
    expect(onClose).toHaveBeenCalled();
  });

  it("closes with no PATCH when saved with no edits staged", async () => {
    mockedListSections.mockResolvedValue(ok([makeSection()]));
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(<OutlineEditorModal courseId="course-1" open onClose={onClose} onApplied={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: /save changes/i }));

    expect(mockedEditOutline).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("keeps the staged draft visible and shows an error banner when applying fails", async () => {
    mockedListSections.mockResolvedValue(ok([makeSection()]));
    mockedEditOutline.mockResolvedValue(err(500));
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(<OutlineEditorModal courseId="course-1" open onClose={onClose} onApplied={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "Chapter One" }));
    const input = screen.getByRole("textbox", { name: /rename chapter one/i });
    await user.clear(input);
    await user.type(input, "Renamed{Enter}");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /applying your outline edits failed/i,
    );
    expect(onClose).not.toHaveBeenCalled();
    // The staged draft survived the failed attempt — same button the user
    // would click again to retry, no separate control needed.
    expect(screen.getByRole("button", { name: "Renamed" })).toBeInTheDocument();
  });

  it("Escape calls onClose", async () => {
    mockedListSections.mockResolvedValue(ok([makeSection()]));
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(<OutlineEditorModal courseId="course-1" open onClose={onClose} onApplied={vi.fn()} />);
    await screen.findByRole("dialog", { name: /edit outline/i });

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
