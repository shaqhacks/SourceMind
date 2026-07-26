import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import NotePopover from "@/components/reader/NotePopover";

function anchorRect(): DOMRect {
  return {
    top: 200,
    bottom: 200,
    left: 100,
    right: 100,
    width: 0,
    height: 0,
    x: 100,
    y: 200,
    toJSON: () => ({}),
  } as DOMRect;
}

describe("NotePopover", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("composer mode: saves the typed text and has no Delete button", async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(<NotePopover anchorRect={anchorRect()} onSave={onSave} onClose={vi.fn()} />);

    expect(screen.getByRole("dialog", { name: "Add note" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "Note" }), "remember this");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith("remember this");
  });

  it("Save is disabled for an empty/whitespace-only note (note_md is required)", async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(<NotePopover anchorRect={anchorRect()} onSave={onSave} onClose={vi.fn()} />);

    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Note" }), "   ");
    expect(save).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("edit mode: prefills the note, exposes Delete, and saves an edit", async () => {
    const onSave = vi.fn();
    const onDelete = vi.fn();
    const user = userEvent.setup();
    render(
      <NotePopover
        initialNote="original"
        anchorRect={anchorRect()}
        onSave={onSave}
        onDelete={onDelete}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole("dialog", { name: "Edit note" })).toBeInTheDocument();
    const textarea = screen.getByRole("textbox", { name: "Note" });
    expect(textarea).toHaveValue("original");

    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(onDelete).toHaveBeenCalledTimes(1);

    await user.clear(textarea);
    await user.type(textarea, "edited");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave).toHaveBeenCalledWith("edited");
  });
});
