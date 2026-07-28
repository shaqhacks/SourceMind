import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { formatRelativeDate } from "@/components/tests/testsFormat";

describe("formatRelativeDate", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // Local noon, not midnight — exercises startOfDay's own truncation
    // rather than coincidentally already being at a day boundary.
    vi.setSystemTime(new Date(2026, 0, 15, 12, 0, 0));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns 'today' for a timestamp earlier the same day", () => {
    expect(formatRelativeDate(new Date(2026, 0, 15, 8, 0, 0).toISOString())).toBe("today");
  });

  it("returns 'yesterday' for exactly one day back", () => {
    expect(formatRelativeDate(new Date(2026, 0, 14, 8, 0, 0).toISOString())).toBe("yesterday");
  });

  it("returns 'N days ago' for a handful of days back", () => {
    expect(formatRelativeDate(new Date(2026, 0, 10, 8, 0, 0).toISOString())).toBe("5 days ago");
  });

  it("falls back to a short absolute date once 14+ days have passed", () => {
    const then = new Date(2026, 0, 1, 8, 0, 0);
    const expected = then.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    expect(formatRelativeDate(then.toISOString())).toBe(expected);
  });
});
