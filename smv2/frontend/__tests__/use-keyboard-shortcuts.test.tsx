import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useKeyboardShortcuts } from "@/lib/hooks/useKeyboardShortcuts";

function ShortcutProbe({ onTrigger }: { onTrigger: () => void }) {
  useKeyboardShortcuts({ a: onTrigger });
  return (
    <div>
      <input aria-label="text field" />
      <textarea aria-label="text area" />
      <div aria-label="editable" contentEditable suppressContentEditableWarning />
      <button aria-label="plain button">click</button>
    </div>
  );
}

describe("useKeyboardShortcuts", () => {
  afterEach(() => {
    cleanup();
  });

  it("fires the mapped handler when the key is pressed outside any editable element", () => {
    const onTrigger = vi.fn();
    render(<ShortcutProbe onTrigger={onTrigger} />);

    fireEvent.keyDown(screen.getByLabelText("plain button"), { key: "a" });

    expect(onTrigger).toHaveBeenCalledTimes(1);
  });

  it("ignores a keydown originating from an input", () => {
    const onTrigger = vi.fn();
    render(<ShortcutProbe onTrigger={onTrigger} />);

    fireEvent.keyDown(screen.getByLabelText("text field"), { key: "a" });

    expect(onTrigger).not.toHaveBeenCalled();
  });

  it("ignores a keydown originating from a textarea", () => {
    const onTrigger = vi.fn();
    render(<ShortcutProbe onTrigger={onTrigger} />);

    fireEvent.keyDown(screen.getByLabelText("text area"), { key: "a" });

    expect(onTrigger).not.toHaveBeenCalled();
  });

  it("ignores a keydown originating from a contentEditable element", () => {
    const onTrigger = vi.fn();
    render(<ShortcutProbe onTrigger={onTrigger} />);

    fireEvent.keyDown(screen.getByLabelText("editable"), { key: "a" });

    expect(onTrigger).not.toHaveBeenCalled();
  });

  it("stops calling the handler once the registering component unmounts", () => {
    const onTrigger = vi.fn();
    const { unmount } = render(<ShortcutProbe onTrigger={onTrigger} />);
    unmount();

    fireEvent.keyDown(window, { key: "a" });

    expect(onTrigger).not.toHaveBeenCalled();
  });

  it("lets a scope registered later suppress an earlier one, restoring it on unmount", () => {
    // Mirrors the real CourseReader + ShortcutsOverlay pattern: the reader
    // shell's arrow-key scope is registered first and stays mounted, then
    // the overlay's "escape" scope is registered later (when it opens) and
    // takes over until it unmounts/disables.
    const earlier = vi.fn();
    const later = vi.fn();

    render(<ShortcutProbe onTrigger={earlier} />);
    fireEvent.keyDown(window, { key: "a" });
    expect(earlier).toHaveBeenCalledTimes(1);

    const { unmount: unmountLater } = render(<ShortcutProbe onTrigger={later} />);
    fireEvent.keyDown(window, { key: "a" });
    expect(later).toHaveBeenCalledTimes(1);
    expect(earlier).toHaveBeenCalledTimes(1); // unchanged — still suppressed

    unmountLater();
    fireEvent.keyDown(window, { key: "a" });
    expect(earlier).toHaveBeenCalledTimes(2); // resumes handling the key
  });
});
