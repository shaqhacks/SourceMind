import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import SelectionContextPill from "@/components/reader/SelectionContextPill";

describe("SelectionContextPill", () => {
  afterEach(() => {
    cleanup();
  });

  it("shows the word count, the full (untruncated) snippet, and the full text as a hover title", () => {
    // Nine words, counted deliberately, and short enough (<=50 chars) to
    // stay untruncated in the visible snippet.
    const exact = "one two three four five six seven eight nine";

    render(<SelectionContextPill exact={exact} onRemove={vi.fn()} />);

    const pill = screen.getByTitle(exact);
    expect(pill).toHaveTextContent("9 words");
    expect(pill).toHaveTextContent(exact);
  });

  it("truncates a long passage to roughly the first 50 characters, with an ellipsis", () => {
    const exact = "abcdefghij".repeat(10); // 100 chars, no whitespace

    render(<SelectionContextPill exact={exact} onRemove={vi.fn()} />);

    const pill = screen.getByTitle(exact);
    expect(pill).not.toHaveTextContent(exact);
    expect(pill.textContent).toContain(exact.slice(0, 50));
    expect(pill.textContent).toContain("…");
  });

  it("does not truncate a passage already at or under the snippet length", () => {
    const exact = "short passage";

    render(<SelectionContextPill exact={exact} onRemove={vi.fn()} />);

    const pill = screen.getByTitle(exact);
    expect(pill).toHaveTextContent(exact);
    expect(pill.textContent).not.toContain("…");
  });

  // Single-word edge case: always "words" (never "word") — the simplest
  // form, chosen over a singular/plural branch for a cosmetic label.
  it("uses plural 'words' even for a single-word passage", () => {
    render(<SelectionContextPill exact="Word" onRemove={vi.fn()} />);

    expect(screen.getByTitle("Word")).toHaveTextContent("1 words");
  });

  it("the × button calls onRemove", async () => {
    const onRemove = vi.fn();
    const user = userEvent.setup();

    render(<SelectionContextPill exact="some text" onRemove={onRemove} />);

    await user.click(screen.getByRole("button", { name: "Remove context" }));

    expect(onRemove).toHaveBeenCalledTimes(1);
  });
});
