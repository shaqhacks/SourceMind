import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import OutlineConfirmation from "@/components/upload/OutlineConfirmation";
import type { SectionOut } from "@/lib/api/client";

function makeSection(overrides: Partial<SectionOut> = {}): SectionOut {
  return {
    id: "sec-1",
    title: "Chapter",
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

const SECTIONS: SectionOut[] = [
  makeSection({ id: "sec-1", title: "Intro", order_index: 0, page_start: 1, page_end: 5 }),
  makeSection({ id: "sec-2", title: "Middle", order_index: 1, page_start: 6, page_end: 10 }),
  makeSection({ id: "sec-3", title: "End", order_index: 2, page_start: 11, page_end: 15 }),
];

describe("OutlineConfirmation", () => {
  afterEach(() => {
    cleanup();
  });

  it("lists every detected chapter with its title and page range", () => {
    render(<OutlineConfirmation sections={SECTIONS} onAccept={vi.fn()} />);

    expect(screen.getByText("Intro")).toBeInTheDocument();
    expect(screen.getByText("p.1–5")).toBeInTheDocument();
    expect(screen.getByText("Middle")).toBeInTheDocument();
    expect(screen.getByText("End")).toBeInTheDocument();
  });

  it("accepts with no operations when nothing was edited", async () => {
    const onAccept = vi.fn();
    const user = userEvent.setup();
    render(<OutlineConfirmation sections={SECTIONS} onAccept={onAccept} />);

    await user.click(screen.getByRole("button", { name: /accept outline/i }));

    expect(onAccept).toHaveBeenCalledWith([]);
  });

  it("accepts on plain Enter, from outside any input", async () => {
    const onAccept = vi.fn();
    const user = userEvent.setup();
    render(<OutlineConfirmation sections={SECTIONS} onAccept={onAccept} />);

    await user.keyboard("{Enter}");

    expect(onAccept).toHaveBeenCalledWith([]);
  });

  it("renaming a chapter and accepting issues exactly one rename op", async () => {
    const onAccept = vi.fn();
    const user = userEvent.setup();
    render(<OutlineConfirmation sections={SECTIONS} onAccept={onAccept} />);

    await user.click(screen.getByRole("button", { name: "Middle" }));
    const input = screen.getByRole("textbox", { name: /rename middle/i });
    await user.clear(input);
    await user.type(input, "Middle Chapter");
    await user.keyboard("{Enter}"); // confirms the rename (blurs the field)

    await user.click(screen.getByRole("button", { name: /accept outline/i }));

    expect(onAccept).toHaveBeenCalledWith([
      { type: "rename", section_id: "sec-2", title: "Middle Chapter" },
    ]);
  });

  it("Enter while actively renaming confirms the rename instead of accepting the whole outline", async () => {
    const onAccept = vi.fn();
    const user = userEvent.setup();
    render(<OutlineConfirmation sections={SECTIONS} onAccept={onAccept} />);

    await user.click(screen.getByRole("button", { name: "Middle" }));
    const input = screen.getByRole("textbox", { name: /rename middle/i });
    await user.clear(input);
    await user.type(input, "Renamed{Enter}");

    // The rename input should have exited edit mode (no more textbox)...
    expect(screen.queryByRole("textbox", { name: /rename middle/i })).not.toBeInTheDocument();
    // ...and Enter must NOT have already triggered a whole-outline accept.
    expect(onAccept).not.toHaveBeenCalled();
  });

  it("deleting a chapter removes it from the list and issues a delete op", async () => {
    const onAccept = vi.fn();
    const user = userEvent.setup();
    render(<OutlineConfirmation sections={SECTIONS} onAccept={onAccept} />);

    const middleRow = screen.getByText("Middle").closest("li")!;
    await user.click(within(middleRow).getByRole("button", { name: /delete/i }));

    expect(screen.queryByText("Middle")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /accept outline/i }));
    expect(onAccept).toHaveBeenCalledWith([{ type: "delete", section_id: "sec-2" }]);
  });

  it("moving a chapter up with the reorder control and accepting issues a reorder op", async () => {
    const onAccept = vi.fn();
    const user = userEvent.setup();
    render(<OutlineConfirmation sections={SECTIONS} onAccept={onAccept} />);

    await user.click(screen.getByRole("button", { name: /move end up/i }));
    await user.click(screen.getByRole("button", { name: /accept outline/i }));

    expect(onAccept).toHaveBeenCalledWith([
      { type: "reorder", order: ["sec-1", "sec-3", "sec-2"] },
    ]);
  });

  it("selecting two adjacent chapters allows merging, and shows the reset-review-state warning", async () => {
    const onAccept = vi.fn();
    const user = userEvent.setup();
    render(<OutlineConfirmation sections={SECTIONS} onAccept={onAccept} />);

    expect(
      screen.getByText(/merging or splitting resets review state/i),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: /select intro/i }));
    await user.click(screen.getByRole("checkbox", { name: /select middle/i }));

    const mergeButton = screen.getByRole("button", { name: /merge selected/i });
    expect(mergeButton).toBeEnabled();
    await user.click(mergeButton);

    // One "will merge" note per row in the merged group (sec-1 and sec-2).
    expect(screen.getAllByText(/will merge with the adjacent selected chapters/i)).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: /accept outline/i }));
    expect(onAccept).toHaveBeenCalledWith([
      { type: "merge", section_ids: ["sec-1", "sec-2"] },
    ]);
  });

  it("disables merging non-adjacent chapters", async () => {
    const user = userEvent.setup();
    render(<OutlineConfirmation sections={SECTIONS} onAccept={vi.fn()} />);

    await user.click(screen.getByRole("checkbox", { name: /select intro/i }));
    await user.click(screen.getByRole("checkbox", { name: /select end/i }));

    expect(screen.getByRole("button", { name: /merge selected/i })).toBeDisabled();
    expect(screen.getByText(/only adjacent chapters can be merged/i)).toBeInTheDocument();
  });

  it("splitting a chapter at a page and accepting issues a split op", async () => {
    const onAccept = vi.fn();
    const user = userEvent.setup();
    render(<OutlineConfirmation sections={SECTIONS} onAccept={onAccept} />);

    const endRow = screen.getByText("End").closest("li")!;
    await user.type(within(endRow).getByRole("spinbutton", { name: /split page for end/i }), "13");
    await user.click(within(endRow).getByRole("button", { name: /^split$/i }));

    expect(screen.getByText(/will split at page 13/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /accept outline/i }));
    expect(onAccept).toHaveBeenCalledWith([{ type: "split", section_id: "sec-3", at_page: 13 }]);
  });
});
