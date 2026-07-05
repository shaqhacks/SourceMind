import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import TypographyControls from "@/components/TypographyControls";
import { TYPOGRAPHY_STORAGE_KEY } from "@/lib/hooks/useTypographyPrefs";

describe("TypographyControls", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("opens the panel and persists a font size change", async () => {
    const user = userEvent.setup();
    render(<TypographyControls />);

    await user.click(screen.getByRole("button", { name: /typography settings/i }));
    fireEvent.change(screen.getByRole("slider", { name: /font size/i }), {
      target: { value: "20" },
    });

    expect(screen.getByText("20px")).toBeInTheDocument();
    const stored = JSON.parse(window.localStorage.getItem(TYPOGRAPHY_STORAGE_KEY) ?? "{}");
    expect(stored.fontSize).toBe(20);
  });

  it("persists measure and line-height changes independently", async () => {
    const user = userEvent.setup();
    render(<TypographyControls />);

    await user.click(screen.getByRole("button", { name: /typography settings/i }));
    fireEvent.change(screen.getByRole("slider", { name: /line width/i }), {
      target: { value: "80" },
    });
    fireEvent.change(screen.getByRole("slider", { name: /line height/i }), {
      target: { value: "1.8" },
    });

    const stored = JSON.parse(window.localStorage.getItem(TYPOGRAPHY_STORAGE_KEY) ?? "{}");
    expect(stored.measure).toBe(80);
    expect(stored.lineHeight).toBe(1.8);
  });

  it("closes the panel on Escape", async () => {
    const user = userEvent.setup();
    render(<TypographyControls />);

    await user.click(screen.getByRole("button", { name: /typography settings/i }));
    expect(screen.getByRole("group", { name: /typography settings/i })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("group", { name: /typography settings/i })).not.toBeInTheDocument();
  });

  it("persists a value across a remount", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<TypographyControls />);

    await user.click(screen.getByRole("button", { name: /typography settings/i }));
    fireEvent.change(screen.getByRole("slider", { name: /font size/i }), {
      target: { value: "22" },
    });
    unmount();

    render(<TypographyControls />);
    await user.click(screen.getByRole("button", { name: /typography settings/i }));
    expect(screen.getByText("22px")).toBeInTheDocument();
  });
});
