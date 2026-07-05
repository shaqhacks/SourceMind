import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useDialogFocus } from "@/lib/hooks/useDialogFocus";

function TrapHarness({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useDialogFocus<HTMLDivElement>(open);
  if (!open) return null;
  return (
    <div ref={ref} role="dialog" tabIndex={-1}>
      <button type="button">First</button>
      <button type="button">Last</button>
      <button type="button" onClick={onClose}>
        Close
      </button>
    </div>
  );
}

function NoTrapHarness({ open }: { open: boolean }) {
  const ref = useDialogFocus<HTMLDivElement>(open, { trap: false });
  if (!open) return null;
  return (
    <div ref={ref} role="dialog" tabIndex={-1}>
      <button type="button">Only</button>
    </div>
  );
}

describe("useDialogFocus", () => {
  afterEach(() => {
    cleanup();
    document.body.innerHTML = "";
  });

  it("moves focus to the first focusable element on open", () => {
    render(
      <>
        <button type="button">Trigger</button>
        <TrapHarness open onClose={() => {}} />
      </>,
    );

    expect(screen.getByRole("button", { name: "First" })).toHaveFocus();
  });

  it("restores focus to the trigger once closed", () => {
    const trigger = document.createElement("button");
    trigger.textContent = "Trigger";
    document.body.appendChild(trigger);
    trigger.focus();
    expect(trigger).toHaveFocus();

    const { rerender } = render(<TrapHarness open onClose={() => {}} />);
    expect(trigger).not.toHaveFocus();

    rerender(<TrapHarness open={false} onClose={() => {}} />);
    expect(trigger).toHaveFocus();
  });

  it("traps Tab within the dialog's focusable elements (last -> first, first via shift+tab -> last)", () => {
    render(<TrapHarness open onClose={() => {}} />);

    const first = screen.getByRole("button", { name: "First" });
    const last = screen.getByRole("button", { name: "Close" });

    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(first).toHaveFocus();

    first.focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(last).toHaveFocus();
  });

  it("with trap:false, does not intercept Tab (no cycling)", () => {
    render(
      <>
        <NoTrapHarness open />
        <button type="button">After</button>
      </>,
    );

    const only = screen.getByRole("button", { name: "Only" });
    only.focus();
    const event = fireEvent.keyDown(document, { key: "Tab" });
    // preventDefault would return false from dispatchEvent; trap:false
    // must not call preventDefault, so the native event proceeds untouched.
    expect(event).toBe(true);
  });
});
