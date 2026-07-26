import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AppShell from "@/components/AppShell";

let mockPathname = "/";

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
}));

// The sidebar is its own data-fetching client component with its own
// coverage; here it only matters whether AppShell mounts it per route.
vi.mock("@/components/AppSidebar", () => ({
  default: () => <nav data-testid="app-sidebar" />,
}));

describe("AppShell", () => {
  afterEach(() => {
    cleanup();
    mockPathname = "/";
  });

  it("bounds itself to the viewport height and never allows itself to scroll — only its main content area does", () => {
    render(
      <AppShell header={<div>header content</div>}>
        <p>page content</p>
      </AppShell>,
    );

    const main = screen.getByRole("main");
    // Structure: shell > (sidebar row) > main — the shell root is the
    // row's parent.
    const shell = main.parentElement!.parentElement as HTMLElement;

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
    // The sidebar row must be height-bounded too, or main never clips.
    expect(main.parentElement!.className).toMatch(/\bmin-h-0\b/);
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

  it("mounts the app sidebar on top-level surfaces", () => {
    mockPathname = "/flashcards";
    render(
      <AppShell header={<div>h</div>}>
        <p>c</p>
      </AppShell>,
    );
    expect(screen.getByTestId("app-sidebar")).toBeInTheDocument();
  });

  it.each(["/course/abc123", "/course/abc123/test/at-1", "/review"])(
    "skips the app sidebar on %s — those routes manage their own panels",
    (pathname) => {
      mockPathname = pathname;
      render(
        <AppShell header={<div>h</div>}>
          <p>c</p>
        </AppShell>,
      );
      expect(screen.queryByTestId("app-sidebar")).not.toBeInTheDocument();
    },
  );

  it("keeps the app sidebar on the per-course skill map (it is a top-level surface)", () => {
    mockPathname = "/course/abc123/skills";
    render(
      <AppShell header={<div>h</div>}>
        <p>c</p>
      </AppShell>,
    );
    expect(screen.getByTestId("app-sidebar")).toBeInTheDocument();
  });
});
