import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import ErrorBanner from "@/components/ErrorBanner";

describe("ErrorBanner", () => {
  it("renders the message without a retry button for a 404", () => {
    render(<ErrorBanner status={404} message="Not found" onRetry={vi.fn()} />);

    expect(screen.getByText("Not found")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
  });

  it("renders a retry button for a 500 and calls onRetry when clicked", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    render(<ErrorBanner status={500} message="Server error" onRetry={onRetry} />);

    const button = screen.getByRole("button", { name: /retry/i });
    expect(button).toBeInTheDocument();

    await user.click(button);
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("treats a missing status (network failure) as retryable", () => {
    render(<ErrorBanner message="Network error" onRetry={vi.fn()} />);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});
