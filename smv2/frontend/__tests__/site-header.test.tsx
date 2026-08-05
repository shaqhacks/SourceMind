import { cleanup, render, screen } from "@testing-library/react";
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
}));

vi.mock("@/lib/api/client", () => ({
  getReviewSummary: vi.fn().mockResolvedValue({ status: 200, ok: true, data: undefined }),
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
});
