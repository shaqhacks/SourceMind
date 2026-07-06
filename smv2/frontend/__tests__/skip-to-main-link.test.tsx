import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SkipToMainLink from "@/components/SkipToMainLink";

describe("SkipToMainLink", () => {
  it("is the first tabbable element and targets #main-content", () => {
    render(<SkipToMainLink />);

    const link = screen.getByRole("link", { name: /skip to main content/i });
    expect(link).toHaveAttribute("href", "#main-content");
  });

  it("is visually hidden until focused", () => {
    render(<SkipToMainLink />);

    const link = screen.getByRole("link", { name: /skip to main content/i });
    expect(link).toHaveClass("sr-only");
    expect(link).toHaveClass("focus:not-sr-only");
  });
});
