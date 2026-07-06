import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SiteHeader from "@/components/SiteHeader";

let mockPathname = "/";

vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
}));

vi.mock("@/lib/api/client", () => ({
  getReviewSummary: vi.fn().mockResolvedValue({ status: 200, ok: true, data: undefined }),
}));

describe("SiteHeader", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    mockPathname = "/";
  });

  it("titles the header with a keyboard-focusable link back to the dashboard", () => {
    render(<SiteHeader />);

    const link = screen.getByRole("link", { name: "SourceMind" });
    expect(link).toHaveAttribute("href", "/");
    expect(link.tagName).toBe("A");
  });
});
