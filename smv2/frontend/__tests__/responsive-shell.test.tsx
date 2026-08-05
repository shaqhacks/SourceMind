import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AppShell from "@/components/AppShell";
import SiteHeader from "@/components/SiteHeader";
import { listCourses } from "@/lib/api/client";

let mockPathname = "/";

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ push: vi.fn() }),
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
  searchCourse: vi.fn().mockResolvedValue({ status: 200, ok: true, data: { items: [] } }),
}));

const realMatchMedia = window.matchMedia;
const mockedListCourses = vi.mocked(listCourses);

function setViewport(width: number): void {
  Object.defineProperty(window, "innerWidth", {
    configurable: true,
    writable: true,
    value: width,
  });
  window.matchMedia = ((query: string) => {
    const min = /\(min-width:\s*(\d+)px\)/.exec(query)?.[1];
    const max = /\(max-width:\s*(\d+)px\)/.exec(query)?.[1];
    const matches =
      (min ? width >= Number(min) : true) && (max ? width <= Number(max) : true);
    return {
      matches,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => true,
    } as MediaQueryList;
  }) as typeof window.matchMedia;
  window.dispatchEvent(new Event("resize"));
}

function renderShell(width: number, pathname = "/search") {
  mockPathname = pathname;
  setViewport(width);
  return render(
    <AppShell header={<SiteHeader />}>
      <a href="#after">Focusable page link</a>
    </AppShell>,
  );
}

describe("responsive shell", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockedListCourses.mockResolvedValue({ status: 200, ok: true, data: [] });
    mockPathname = "/search";
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    window.localStorage.clear();
    window.matchMedia = realMatchMedia;
    mockPathname = "/";
  });

  it("renders 320px as a compact header with overlay navigation, not a persistent sidebar", async () => {
    const user = userEvent.setup();
    renderShell(320);

    expect(screen.queryByRole("navigation", { name: "App" })).not.toBeInTheDocument();
    const trigger = screen.getByRole("button", { name: "Open navigation" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await user.click(trigger);

    const drawer = screen.getByRole("dialog", { name: "App navigation" });
    expect(drawer).toHaveAttribute("aria-modal", "true");
    expect(within(drawer).getByRole("navigation", { name: "App" })).toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });

  it("renders 768px as a tablet drawer instead of a persistent sidebar", async () => {
    const user = userEvent.setup();
    renderShell(768);

    expect(screen.queryByRole("navigation", { name: "App" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open navigation" }));

    expect(screen.getByRole("dialog", { name: "App navigation" })).toHaveAttribute(
      "data-layout",
      "tablet",
    );
  });

  it.each([
    [320, "/course/abc", "mobile"],
    [768, "/review", "tablet"],
  ] as const)(
    "opens transient app navigation at %ipx on panel-owning route %s",
    async (width, pathname, layout) => {
      const user = userEvent.setup();
      renderShell(width, pathname);

      expect(screen.queryByRole("navigation", { name: "App" })).not.toBeInTheDocument();
      const trigger = screen.getByRole("button", { name: "Open navigation" });

      await user.click(trigger);

      const drawer = screen.getByRole("dialog", { name: "App navigation" });
      expect(drawer).toHaveAttribute("data-layout", layout);
      expect(within(drawer).getByRole("navigation", { name: "App" })).toBeInTheDocument();

      fireEvent.keyDown(document, { key: "Escape" });
      expect(screen.queryByRole("dialog", { name: "App navigation" })).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    },
  );

  it("renders 1024px as the desktop persistent sidebar", () => {
    renderShell(1024);

    expect(screen.getByRole("navigation", { name: "App" })).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "App navigation" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toBeInTheDocument();
  });

  it("keeps 1440px on the desktop structure without horizontal overflow classes", () => {
    renderShell(1440);

    const main = screen.getByRole("main");
    const shell = main.parentElement!.parentElement as HTMLElement;
    expect(screen.getByRole("navigation", { name: "App" })).toBeInTheDocument();
    expect(shell).toHaveAttribute("data-layout", "desktop");
    expect(shell.className).toMatch(/\boverflow-hidden\b/);
  });

  it("traps focus while the transient drawer is open and restores focus after close", async () => {
    const user = userEvent.setup();
    renderShell(320);

    const trigger = screen.getByRole("button", { name: "Open navigation" });
    await user.click(trigger);

    const drawer = screen.getByRole("dialog", { name: "App navigation" });
    const close = within(drawer).getByRole("button", { name: "Close navigation" });
    close.focus();

    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(drawer).toContainElement(document.activeElement as HTMLElement);

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("dialog", { name: "App navigation" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
