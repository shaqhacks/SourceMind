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
  it("renders ghost variant with hover token classes", () => {
    render(<Button variant="ghost">More</Button>);
    const btn = screen.getByRole("button", { name: "More" });
    expect(btn.className).toContain("hover:bg-muted-foreground/10");
  });
  it("renders danger variant with serious status classes", () => {
    render(<Button variant="danger">Delete</Button>);
    const btn = screen.getByRole("button", { name: "Delete" });
    expect(btn.className).toContain("text-status-serious");
  });
  it("renders sm size with compact spacing classes", () => {
    render(<Button size="sm">Tiny</Button>);
    const btn = screen.getByRole("button", { name: "Tiny" });
    expect(btn.className).toContain("px-2 py-1 text-xs");
  });
});

describe("Card", () => {
  it("tinted variant uses accent-soft", () => {
    const { container } = render(<Card variant="tinted">x</Card>);
    expect((container.firstChild as HTMLElement).className).toContain("bg-accent-soft");
  });
  it("defaults to plain variant with raised surface", () => {
    const { container } = render(<Card>x</Card>);
    expect((container.firstChild as HTMLElement).className).toContain("bg-surface-raised");
  });
  it("interactive adds hover border affordance", () => {
    const { container } = render(<Card interactive>x</Card>);
    expect((container.firstChild as HTMLElement).className).toContain(
      "hover:border-muted-foreground",
    );
  });
});

describe("Badge", () => {
  it("always renders a glyph beside the label (not color-alone)", () => {
    render(<Badge tone="good">Ready</Badge>);
    const badge = screen.getByText("Ready").closest("span")!;
    expect(badge.textContent!.length).toBeGreaterThan("Ready".length);
    expect(badge.className).toContain("bg-status-good-soft");
  });
  it.each([
    ["warning", "bg-status-warning-soft"],
    ["serious", "bg-status-serious-soft"],
    ["neutral", "bg-muted-foreground/10"],
    ["accent", "bg-accent-soft"],
  ] as const)("%s tone applies its soft background class", (tone, expected) => {
    render(<Badge tone={tone}>Label</Badge>);
    const badge = screen.getByText("Label").closest("span")!;
    expect(badge.className).toContain(expected);
  });
  it("icon prop overrides the default glyph and stays aria-hidden", () => {
    render(
      <Badge tone="good" icon="★">
        Starred
      </Badge>,
    );
    const badge = screen.getByText("Starred").closest("span")!;
    const glyph = badge.querySelector('[aria-hidden="true"]')!;
    expect(glyph.textContent).toBe("★");
    expect(badge.textContent).not.toContain("✓");
  });
});
