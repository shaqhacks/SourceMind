import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import UsageFooter from "@/components/reader/UsageFooter";
import { getLlmUsage } from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({
  getLlmUsage: vi.fn(),
}));

const mockedGetLlmUsage = vi.mocked(getLlmUsage);

describe("UsageFooter", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders nothing while usage hasn't loaded yet", () => {
    mockedGetLlmUsage.mockReturnValue(new Promise(() => {}));
    const { container } = render(<UsageFooter courseId="course-1" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows call count and cost once loaded", async () => {
    mockedGetLlmUsage.mockResolvedValue({
      status: 200,
      ok: true,
      data: { calls: 7, input_tokens: 1000, output_tokens: 2000, est_cost_usd: 1.236 },
    });

    render(<UsageFooter courseId="course-1" />);

    expect(await screen.findByText(/llm usage: 7 calls · \$1\.24/i)).toBeInTheDocument();
    expect(mockedGetLlmUsage).toHaveBeenCalledWith("course-1");
  });

  it("uses singular 'call' for exactly one call", async () => {
    mockedGetLlmUsage.mockResolvedValue({
      status: 200,
      ok: true,
      data: { calls: 1, input_tokens: 100, output_tokens: 200, est_cost_usd: 0.01 },
    });

    render(<UsageFooter courseId="course-1" />);

    expect(await screen.findByText(/llm usage: 1 call ·/i)).toBeInTheDocument();
  });
});
