import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AppSidebar from "@/components/AppSidebar";

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
  getReviewSummary: vi.fn().mockResolvedValue({ status: 200, ok: true, data: { due_total: 0, courses: [] } }),
  getLlmUsage: vi.fn().mockResolvedValue({ status: 200, ok: true, data: { calls: 0, input_tokens: 0, output_tokens: 0, est_cost_usd: 0 } }),
}));

describe("AppSidebar", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    mockPathname = "/";
    delete process.env.NEXT_PUBLIC_SMV2_AI_READINESS_UI;
  });

  it("shows Jobs and Settings as top-level navigation links", () => {
    render(<AppSidebar />);

    expect(screen.getByRole("link", { name: "Jobs" })).toHaveAttribute("href", "/jobs");
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
  });

  it("keeps Jobs and Settings visible when credential editing is flag-disabled", () => {
    process.env.NEXT_PUBLIC_SMV2_AI_READINESS_UI = "0";

    render(<AppSidebar />);

    expect(screen.getByRole("link", { name: "Jobs" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings" })).toBeInTheDocument();
  });

  it("marks Settings current on the settings route", () => {
    mockPathname = "/settings";

    render(<AppSidebar />);

    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("aria-current", "page");
  });
});
