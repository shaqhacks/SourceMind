/**
 * Pure preview of "if I grade this card N, when's it next due" — mirrors
 * backend/app/services/srs_service.py::schedule_next's interval formulas
 * (grades 2-4; grade 1/Again is a fixed 10-minute delay, not a day count,
 * so it's represented as `null` here rather than 0 days). Reads the same
 * ReviewQueueCardOut.{interval_days,ease,reps} fields the backend itself
 * uses for the same card — never guesses at state it doesn't have, and
 * never mutates/persists anything (that's schedule_next's real job on the
 * backend, invoked at actual grade time via POST /api/cards/{id}/grade).
 *
 * Kept in lockstep with srs_service's two documented conventions:
 * - `baseline(reps)`: 1.0 day at reps===0, 6.0 days at reps===1, else the
 *   card's own current interval_days (the "bootstrap trap", ADR-007).
 * - Ease multiplications use the ease value going INTO this grade, never
 *   the value this same grade would produce — that only applies next time.
 */

export type ReviewGrade = 1 | 2 | 3 | 4;

export interface CardSchedulerState {
  intervalDays: number;
  ease: number;
  reps: number;
}

function baselineInterval(state: CardSchedulerState): number {
  if (state.reps === 0) return 1.0;
  if (state.reps === 1) return 6.0;
  return state.intervalDays;
}

/** Days until the card would next be due for `grade`, or `null` for Again
 * (a fixed 10-minute delay — srs_service's `_AGAIN_DUE_MINUTES`). */
export function previewIntervalDays(grade: ReviewGrade, state: CardSchedulerState): number | null {
  if (grade === 1) return null;

  const baseline = baselineInterval(state);
  if (grade === 2) return baseline * 1.2; // Hard never multiplies by ease
  if (grade === 3) return state.reps < 2 ? baseline : baseline * state.ease;
  return (state.reps < 2 ? baseline : baseline * state.ease) * 1.3; // Easy
}

/** "<10 min" / "1 day" / "N days" — the grade row's sub-label text. */
export function formatIntervalPreview(days: number | null): string {
  if (days === null) return "<10 min";
  const rounded = Math.max(1, Math.round(days));
  return rounded === 1 ? "1 day" : `${rounded} days`;
}
