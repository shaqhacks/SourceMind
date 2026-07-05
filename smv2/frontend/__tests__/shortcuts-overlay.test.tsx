import { useState } from "react";

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import ShortcutsOverlay, { type ShortcutHint } from "@/components/ShortcutsOverlay";

const SHORTCUTS: ShortcutHint[] = [
  { keys: "j", description: "Next chapter" },
  { keys: "k", description: "Previous chapter" },
];

function ControlledOverlay() {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button type="button" onClick={() => setOpen(true)}>
        Open shortcuts
      </button>
      <ShortcutsOverlay open={open} onClose={() => setOpen(false)} shortcuts={SHORTCUTS} />
    </div>
  );
}

describe("ShortcutsOverlay", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders nothing when closed", () => {
    render(<ShortcutsOverlay open={false} onClose={vi.fn()} shortcuts={SHORTCUTS} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows the dialog and moves focus into it when opened", () => {
    render(<ShortcutsOverlay open onClose={vi.fn()} shortcuts={SHORTCUTS} />);

    const dialog = screen.getByRole("dialog", { name: /keyboard shortcuts/i });
    expect(dialog).toBeInTheDocument();
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
  });

  it("calls onClose when Escape is pressed", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<ShortcutsOverlay open onClose={onClose} shortcuts={SHORTCUTS} />);

    await user.keyboard("{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("traps Tab focus inside the dialog instead of letting it escape", async () => {
    const user = userEvent.setup();
    render(<ShortcutsOverlay open onClose={vi.fn()} shortcuts={SHORTCUTS} />);

    // The dialog's only focusable descendant is the Close button, so
    // tabbing forward from it must wrap back onto itself rather than
    // escaping to `document.body`.
    const closeButton = screen.getByRole("button", { name: "Close" });
    expect(document.activeElement).toBe(closeButton);

    await user.tab();
    expect(document.activeElement).toBe(closeButton);

    await user.tab({ shift: true });
    expect(document.activeElement).toBe(closeButton);
  });

  it("opens on demand and restores focus to the triggering element on close", async () => {
    const user = userEvent.setup();
    render(<ControlledOverlay />);

    const trigger = screen.getByRole("button", { name: "Open shortcuts" });
    await user.click(trigger);

    expect(screen.getByRole("dialog", { name: /keyboard shortcuts/i })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.activeElement).toBe(trigger);
  });
});
