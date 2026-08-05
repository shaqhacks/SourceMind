import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AppShell from "@/components/AppShell";
import { listCourses } from "@/lib/api/client";
import { WORKSPACE_MODE_STORAGE_KEY } from "@/lib/hooks/useWorkspaceMode";

let mockPathname = "/";

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
}));

vi.mock("@/lib/hooks/useSidebarCollapsed", () => ({
  useSidebarCollapsed: () => ({ collapsed: false }),
}));

vi.mock("@/components/upload/UploadFlow", () => ({
  default: () => null,
}));

vi.mock("@/lib/api/client", () => ({
  listCourses: vi.fn().mockResolvedValue({ status: 200, ok: true, data: [] }),
  getReviewSummary: vi.fn().mockResolvedValue({
    status: 200,
    ok: true,
    data: { due_total: 0, daily_throughput: 0, backlog_warning: false, courses: [] },
  }),
  getLlmUsage: vi.fn().mockResolvedValue({
    status: 200,
    ok: true,
    data: { calls: 0, input_tokens: 0, output_tokens: 0, est_cost_usd: 0 },
  }),
}));

const mockedListCourses = vi.mocked(listCourses);

describe("AppShell", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockedListCourses.mockResolvedValue({ status: 200, ok: true, data: [] });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    mockPathname = "/";
    window.localStorage.clear();
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
    expect(screen.getByRole("navigation", { name: "App" })).toBeInTheDocument();
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
      expect(screen.queryByRole("navigation", { name: "App" })).not.toBeInTheDocument();
    },
  );

  it("keeps the app sidebar on the per-course skill map (it is a top-level surface)", () => {
    mockPathname = "/course/abc123/skills";
    render(
      <AppShell header={<div>h</div>}>
        <p>c</p>
      </AppShell>,
    );
    expect(screen.getByRole("navigation", { name: "App" })).toBeInTheDocument();
  });

  it("defaults learner mode to hiding instructor-only curriculum and validation links", async () => {
    mockedListCourses.mockResolvedValue({
      status: 200,
      ok: true,
      data: [
        {
          id: "course-1",
          title: "Course One",
          status: "ready",
          section_count: 3,
          failed_asset_count: 0,
          is_sample: false,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          progress: null,
        },
      ],
    });

    render(
      <AppShell header={<div>h</div>}>
        <p>c</p>
      </AppShell>,
    );

    expect(await screen.findByRole("link", { name: "Course One" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Skill map" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Curriculum" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Validate" })).not.toBeInTheDocument();
    expect(screen.queryByText("Instructor tools")).not.toBeInTheDocument();
  });

  it("shows curriculum and validation inside an explicit instructor tools section in instructor mode", async () => {
    window.localStorage.setItem(WORKSPACE_MODE_STORAGE_KEY, "instructor");
    mockedListCourses.mockResolvedValue({
      status: 200,
      ok: true,
      data: [
        {
          id: "course-1",
          title: "Course One",
          status: "ready",
          section_count: 3,
          failed_asset_count: 0,
          is_sample: false,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
          progress: null,
        },
      ],
    });

    render(
      <AppShell header={<div>h</div>}>
        <p>c</p>
      </AppShell>,
    );

    const instructorTools = await screen.findByRole("group", {
      name: "Instructor tools for Course One",
    });

    expect(screen.getByText("Instructor tools")).toBeInTheDocument();
    expect(instructorTools).toContainElement(screen.getByRole("link", { name: "Curriculum" }));
    expect(instructorTools).toContainElement(screen.getByRole("link", { name: "Validate" }));
  });
});
