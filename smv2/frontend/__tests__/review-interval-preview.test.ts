import { describe, expect, it } from "vitest";

import {
  formatIntervalPreview,
  previewIntervalDays,
  type CardSchedulerState,
} from "@/lib/review/intervalPreview";

// Every numeric case here is pinned to backend/app/services/srs_service.py's
// schedule_next math (see tests/test_srs_schedule.py on the backend for the
// source-of-truth table) — not re-derived independently.

const NEW_CARD: CardSchedulerState = { intervalDays: 0.0, ease: 2.5, reps: 0 };
// State after one Good grade: interval_days=1.0 (first bootstrap step), reps=1.
const REVIEWED_ONCE: CardSchedulerState = { intervalDays: 1.0, ease: 2.5, reps: 1 };
// State after two Good grades: interval_days=6.0 (second bootstrap step), reps=2 —
// baseline() now reads the card's own interval_days instead of a fixed step.
const REVIEWED_TWICE: CardSchedulerState = { intervalDays: 6.0, ease: 2.5, reps: 2 };
// A struggling card: ease has been floored down from repeated Again grades.
const LOW_EASE: CardSchedulerState = { intervalDays: 3.0, ease: 1.3, reps: 2 };

describe("previewIntervalDays", () => {
  it("Again (1) is always null — a fixed 10-minute delay, not a day count", () => {
    for (const state of [NEW_CARD, REVIEWED_ONCE, REVIEWED_TWICE, LOW_EASE]) {
      expect(previewIntervalDays(1, state)).toBeNull();
    }
  });

  it("new card: baseline(reps=0)=1.0, Hard/Good/Easy never multiply by ease yet", () => {
    expect(previewIntervalDays(2, NEW_CARD)).toBeCloseTo(1.2); // 1.0 * 1.2
    expect(previewIntervalDays(3, NEW_CARD)).toBeCloseTo(1.0); // reps<2: baseline as-is
    expect(previewIntervalDays(4, NEW_CARD)).toBeCloseTo(1.3); // 1.0 * 1.3
  });

  it("reviewed once (reps=1): baseline(reps=1)=6.0 fixed step, still no ease multiplier", () => {
    expect(previewIntervalDays(2, REVIEWED_ONCE)).toBeCloseTo(7.2); // 6.0 * 1.2
    expect(previewIntervalDays(3, REVIEWED_ONCE)).toBeCloseTo(6.0); // reps<2: baseline as-is
    expect(previewIntervalDays(4, REVIEWED_ONCE)).toBeCloseTo(7.8); // 6.0 * 1.3
  });

  it("reviewed twice (reps=2): baseline is now the card's own interval_days, Good/Easy multiply by ease", () => {
    expect(previewIntervalDays(2, REVIEWED_TWICE)).toBeCloseTo(7.2); // 6.0 * 1.2 — Hard never uses ease
    expect(previewIntervalDays(3, REVIEWED_TWICE)).toBeCloseTo(15.0); // 6.0 * 2.5
    expect(previewIntervalDays(4, REVIEWED_TWICE)).toBeCloseTo(19.5); // 6.0 * 2.5 * 1.3
  });

  it("low ease (repeated Again history): Good/Easy scale down with it, Hard is unaffected", () => {
    expect(previewIntervalDays(2, LOW_EASE)).toBeCloseTo(3.6); // 3.0 * 1.2
    expect(previewIntervalDays(3, LOW_EASE)).toBeCloseTo(3.9); // 3.0 * 1.3
    expect(previewIntervalDays(4, LOW_EASE)).toBeCloseTo(5.07); // 3.0 * 1.3 * 1.3
  });
});

describe("formatIntervalPreview", () => {
  it("renders Again's null as the fixed minute label", () => {
    expect(formatIntervalPreview(null)).toBe("<10 min");
  });

  it("singularizes exactly 1 day", () => {
    expect(formatIntervalPreview(1.0)).toBe("1 day");
  });

  it("rounds to the nearest whole day and pluralizes", () => {
    expect(formatIntervalPreview(1.2)).toBe("1 day");
    expect(formatIntervalPreview(7.8)).toBe("8 days");
    expect(formatIntervalPreview(19.5)).toBe("20 days");
  });

  it("floors at 1 day rather than showing 0", () => {
    expect(formatIntervalPreview(0.4)).toBe("1 day");
  });
});
