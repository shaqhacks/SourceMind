import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";

describe("Button", () => {
  it("renders primary variant with token classes", () => {
    render(<Button variant="primary">Save</Button>);
    const btn = screen.getByRole("button", { name: "Save" });
    expect(btn.className).toContain("bg-foreground");
    expect(btn.className).toContain("text-background");
  });
  it("defaults to secondary md and forwards props", () => {
    render(<Button disabled>Cancel</Button>);
    const btn = screen.getByRole("button", { name: "Cancel" });
    expect(btn).toBeDisabled();
    expect(btn.className).toContain("border-border");
  });
});

describe("Card", () => {
  it("tinted variant uses accent-soft", () => {
    const { container } = render(<Card variant="tinted">x</Card>);
    expect((container.firstChild as HTMLElement).className).toContain("bg-accent-soft");
  });
});

describe("Badge", () => {
  it("always renders a glyph beside the label (not color-alone)", () => {
    render(<Badge tone="good">Ready</Badge>);
    const badge = screen.getByText("Ready").closest("span")!;
    expect(badge.textContent!.length).toBeGreaterThan("Ready".length);
    expect(badge.className).toContain("bg-status-good-soft");
  });
});
