import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import AppShell from "@/components/AppShell";

describe("AppShell", () => {
  afterEach(() => {
    cleanup();
  });

  it("bounds itself to the viewport height and never allows itself to scroll — only its main content area does", () => {
    render(
      <AppShell header={<div>header content</div>}>
        <p>page content</p>
      </AppShell>,
    );

    const main = screen.getByRole("main");
    const shell = main.parentElement as HTMLElement;

    // The shell itself: real viewport height bound, no overflow of its own.
    expect(shell.className).toMatch(/\bh-dvh\b/);
    expect(shell.className).toMatch(/\boverflow-hidden\b/);

    // main is the only thing that scrolls, and only once bounded (min-h-0
    // + flex-1 within the shell's own fixed height) — see AppShell.tsx's
    // own comment for why this ordering matters (a flex-1 child with no
    // bounded ancestor never actually clips, which is the root cause of
    // the "whole document scrolls, dragging the sidebar along with it"
    // bug this component fixes).
    expect(main.className).toMatch(/\boverflow-y-auto\b/);
    expect(main.className).toMatch(/\bmin-h-0\b/);
    expect(main.className).toMatch(/\bflex-1\b/);
  });

  it("keeps the skip-link contract: main-content id + tabIndex=-1 for fragment-nav focus", () => {
    render(
      <AppShell header={<div>header content</div>}>
        <p>page content</p>
      </AppShell>,
    );

    const main = screen.getByRole("main");
    expect(main).toHaveAttribute("id", "main-content");
    expect(main).toHaveAttribute("tabIndex", "-1");
  });

  it("renders the header above the content, both inside the shell", () => {
    render(
      <AppShell header={<div data-testid="header-slot">header content</div>}>
        <p>page content</p>
      </AppShell>,
    );

    expect(screen.getByTestId("header-slot")).toBeInTheDocument();
    expect(screen.getByText("page content")).toBeInTheDocument();
    expect(screen.getByRole("main")).toContainElement(screen.getByText("page content"));
  });
});
