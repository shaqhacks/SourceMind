import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SiteHeader from "@/components/SiteHeader";
import {
  WORKSPACE_MODE_DISCLOSURE_STORAGE_KEY,
  WORKSPACE_MODE_STORAGE_KEY,
} from "@/lib/hooks/useWorkspaceMode";

let mockPathname = "/";

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/client", () => ({
  getReviewSummary: vi.fn().mockResolvedValue({ status: 200, ok: true, data: undefined }),
  searchCourse: vi.fn().mockResolvedValue({ status: 200, ok: true, data: { items: [] } }),
}));

describe("SiteHeader", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    mockPathname = "/";
    window.localStorage.clear();
  });

  it("titles the header with a keyboard-focusable link back to the dashboard", () => {
    render(<SiteHeader />);

    const link = screen.getByRole("link", { name: "SourceMind" });
    expect(link).toHaveAttribute("href", "/");
    expect(link.tagName).toBe("A");
  });

  it("replaces the decorative avatar with a learner-default workspace mode control", () => {
    render(<SiteHeader />);

    expect(screen.queryByText("S")).not.toBeInTheDocument();
    expect(screen.getByText("Workspace mode")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /workspace mode: learner/i })).toBeInTheDocument();
  });

  it("surfaces the command palette search affordance in the header", () => {
    render(<SiteHeader />);

    expect(screen.getByRole("button", { name: "Open command palette" })).toBeInTheDocument();
  });

  it("shows the instructor explanation once before switching modes", async () => {
    const user = userEvent.setup();
    render(<SiteHeader />);

    await user.click(screen.getByRole("button", { name: /workspace mode: learner/i }));
    await user.click(screen.getByRole("menuitemradio", { name: "Instructor" }));

    expect(screen.getByRole("dialog", { name: "Instructor mode" })).toBeInTheDocument();
    expect(window.localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBeNull();

    await user.click(screen.getByRole("button", { name: "Continue to instructor mode" }));

    expect(window.localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBe("instructor");
    expect(window.localStorage.getItem(WORKSPACE_MODE_DISCLOSURE_STORAGE_KEY)).toBe("true");
    expect(screen.queryByRole("dialog", { name: "Instructor mode" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /workspace mode: instructor/i })).toBeInTheDocument();
  });

  it("closes the workspace mode menu on Escape and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    render(<SiteHeader />);

    const trigger = screen.getByRole("button", { name: /workspace mode: learner/i });
    await user.click(trigger);
    expect(screen.getByRole("menu", { name: "Workspace mode" })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("menu", { name: "Workspace mode" })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("closes the workspace mode menu on an outside pointer click", async () => {
    const user = userEvent.setup();
    render(<SiteHeader />);

    const trigger = screen.getByRole("button", { name: /workspace mode: learner/i });
    await user.click(trigger);
    expect(screen.getByRole("menu", { name: "Workspace mode" })).toBeInTheDocument();

    fireEvent.pointerDown(document.body);

    expect(screen.queryByRole("menu", { name: "Workspace mode" })).not.toBeInTheDocument();
  });

  it("cancels the instructor disclosure on Escape without switching modes and restores focus", async () => {
    const user = userEvent.setup();
    render(<SiteHeader />);

    const trigger = screen.getByRole("button", { name: /workspace mode: learner/i });
    await user.click(trigger);
    await user.click(screen.getByRole("menuitemradio", { name: "Instructor" }));

    expect(screen.getByRole("button", { name: "Stay in learner mode" })).toHaveFocus();

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog", { name: "Instructor mode" })).not.toBeInTheDocument();
    expect(window.localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBeNull();
    expect(screen.getByRole("button", { name: /workspace mode: learner/i })).toHaveFocus();
  });

  it("restores focus to the instructor mode control after disclosure cancel and confirm", async () => {
    const user = userEvent.setup();
    render(<SiteHeader />);

    const trigger = screen.getByRole("button", { name: /workspace mode: learner/i });
    await user.click(trigger);
    await user.click(screen.getByRole("menuitemradio", { name: "Instructor" }));
    await user.click(screen.getByRole("button", { name: "Stay in learner mode" }));

    expect(screen.queryByRole("dialog", { name: "Instructor mode" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /workspace mode: learner/i })).toHaveFocus();

    await user.click(screen.getByRole("button", { name: /workspace mode: learner/i }));
    await user.click(screen.getByRole("menuitemradio", { name: "Instructor" }));
    await user.click(screen.getByRole("button", { name: "Continue to instructor mode" }));

    expect(window.localStorage.getItem(WORKSPACE_MODE_STORAGE_KEY)).toBe("instructor");
    expect(screen.getByRole("button", { name: /workspace mode: instructor/i })).toHaveFocus();
  });
});
