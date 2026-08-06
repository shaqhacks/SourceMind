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
    asset_id: null,
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

  it("lists every detected chapter with its number, title, and page range", () => {
    render(<OutlineConfirmation sections={SECTIONS} onAccept={vi.fn()} />);

    expect(screen.getByText("Intro")).toBeInTheDocument();
    expect(screen.getByText("p.1–5")).toBeInTheDocument();
    expect(screen.getByText("Middle")).toBeInTheDocument();
    expect(screen.getByText("End")).toBeInTheDocument();
    // The accessible name stays the bare title (the "N ·" prefix is
    // decorative/aria-hidden) so this button is reachable by title alone.
    expect(screen.getByRole("button", { name: "Intro" })).toBeInTheDocument();
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

  it("renders no Cancel button by default, and one when onCancel is passed", async () => {
    const { rerender } = render(<OutlineConfirmation sections={SECTIONS} onAccept={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument();

    const onCancel = vi.fn();
    rerender(<OutlineConfirmation sections={SECTIONS} onAccept={vi.fn()} onCancel={onCancel} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("renaming a chapter via the title button and accepting issues exactly one rename op", async () => {
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

  it("renaming a chapter via the explicit Rename button opens the same edit field", async () => {
    const onAccept = vi.fn();
    const user = userEvent.setup();
    render(<OutlineConfirmation sections={SECTIONS} onAccept={onAccept} />);

    const middleRow = screen.getByText("Middle").closest("li")!;
    await user.click(within(middleRow).getByRole("button", { name: /^rename$/i }));
    const input = screen.getByRole("textbox", { name: /rename middle/i });
    await user.clear(input);
    await user.type(input, "Renamed{Enter}");

    await user.click(screen.getByRole("button", { name: /accept outline/i }));
    expect(onAccept).toHaveBeenCalledWith([
      { type: "rename", section_id: "sec-2", title: "Renamed" },
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

  it("selecting two adjacent chapters and merging collapses them into one badged row", async () => {
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

    // Middle's own row disappears entirely; Intro's row carries the badge.
    expect(screen.queryByRole("checkbox", { name: /select middle/i })).not.toBeInTheDocument();
    expect(screen.getByText(/merging with 2/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /accept outline/i }));
    expect(onAccept).toHaveBeenCalledWith([
      { type: "merge", section_ids: ["sec-1", "sec-2"] },
    ]);
  });

  it("undoing a staged merge restores both chapters as separate rows", async () => {
    const user = userEvent.setup();
    render(<OutlineConfirmation sections={SECTIONS} onAccept={vi.fn()} />);

    await user.click(screen.getByRole("checkbox", { name: /select intro/i }));
    await user.click(screen.getByRole("checkbox", { name: /select middle/i }));
    await user.click(screen.getByRole("button", { name: /merge selected/i }));
    expect(screen.getByText(/merging with 2/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /undo/i }));

    expect(screen.queryByText(/merging with 2/i)).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /select middle/i })).toBeInTheDocument();
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
    await user.click(within(endRow).getByRole("button", { name: /^split$/i }));
    await user.type(within(endRow).getByRole("spinbutton", { name: /split page for end/i }), "13");
    await user.click(within(endRow).getByRole("button", { name: /^split$/i }));

    expect(screen.getByText(/will split at page 13/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /accept outline/i }));
    expect(onAccept).toHaveBeenCalledWith([{ type: "split", section_id: "sec-3", at_page: 13 }]);
  });

  it("hides Split for sections without a page range", () => {
    render(
      <OutlineConfirmation
        sections={[
          makeSection({
            id: "sec-text",
            title: "Text chapter",
            page_start: null,
            page_end: null,
          }),
        ]}
        onAccept={vi.fn()}
      />,
    );

    const row = screen.getByText("Text chapter").closest("li")!;
    expect(within(row).queryByRole("button", { name: /^split$/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/p\./i)).not.toBeInTheDocument();
  });

  it("undoing a staged split restores the row to its normal editable state", async () => {
    const user = userEvent.setup();
    render(<OutlineConfirmation sections={SECTIONS} onAccept={vi.fn()} />);

    const endRow = screen.getByText("End").closest("li")!;
    await user.click(within(endRow).getByRole("button", { name: /^split$/i }));
    await user.type(within(endRow).getByRole("spinbutton", { name: /split page for end/i }), "13");
    await user.click(within(endRow).getByRole("button", { name: /^split$/i }));

    await user.click(within(endRow).getByRole("button", { name: /undo/i }));

    expect(screen.queryByText(/will split at page 13/i)).not.toBeInTheDocument();
    expect(within(endRow).getByRole("button", { name: /^split$/i })).toBeInTheDocument();
  });

  it("uses caller-supplied heading, description, submit label, and reassurance note", () => {
    render(
      <OutlineConfirmation
        sections={SECTIONS}
        onAccept={vi.fn()}
        heading="Detected outline — 3 chapters from your PDF's bookmarks"
        description="No AI used · instant & free"
        submitLabel="Accept outline & start reading"
        reassuranceNote="You can fix the outline any time from the reader."
      />,
    );

    expect(
      screen.getByText("Detected outline — 3 chapters from your PDF's bookmarks"),
    ).toBeInTheDocument();
    expect(screen.getByText("No AI used · instant & free")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Accept outline & start reading" }),
    ).toBeInTheDocument();
    expect(screen.getByText("You can fix the outline any time from the reader.")).toBeInTheDocument();
  });
});
