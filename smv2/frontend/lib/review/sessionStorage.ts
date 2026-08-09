export type ReviewScope = "available" | "all" | "needs_attention";

export const ACTIVE_REVIEW_SESSION_STORAGE_KEY = "smv2.review.session";
export const COMPLETED_REVIEW_SESSION_STORAGE_KEY = "smv2.review.completedSession";

const SESSION_STORAGE_VERSION = 1;
const COMPLETED_SESSION_TTL_MS = 86_400_000;

export interface ActiveReviewSession {
  version: 1;
  sessionId: string;
  courseId: string;
  scope: ReviewScope;
  chapterLabel: string | null;
  chosenSize: number;
  remainingCardIds: string[];
  gradedTally: Record<number, number>;
  againCardIds: string[];
  startedAt: number;
}

export interface CompletedReviewSession {
  version: 1;
  sessionId: string;
  courseId: string;
  scope: ReviewScope;
  chapterLabel: string | null;
  endedAt: number;
  gradedTally: Record<number, number>;
  againCardIds: string[];
}

function storage(): Storage | null {
  if (typeof window === "undefined") return null;
  return window.localStorage;
}

function isReviewScope(value: unknown): value is ReviewScope {
  return value === "available" || value === "all" || value === "needs_attention";
}

function isNumberTally(value: unknown): value is Record<number, number> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  return Object.entries(value).every(([key, count]) => Number.isInteger(Number(key)) && typeof count === "number");
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function readJson(key: string): unknown | null {
  try {
    const raw = storage()?.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    storage()?.setItem(key, JSON.stringify(value));
  } catch {
    // Persistence is best-effort; review should continue if storage is unavailable.
  }
}

function remove(key: string): void {
  try {
    storage()?.removeItem(key);
  } catch {
    // ignore
  }
}

function isActiveReviewSession(value: unknown): value is ActiveReviewSession {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    v.version === SESSION_STORAGE_VERSION &&
    typeof v.sessionId === "string" &&
    typeof v.courseId === "string" &&
    isReviewScope(v.scope) &&
    (typeof v.chapterLabel === "string" || v.chapterLabel === null) &&
    typeof v.chosenSize === "number" &&
    isStringArray(v.remainingCardIds) &&
    isNumberTally(v.gradedTally) &&
    isStringArray(v.againCardIds) &&
    typeof v.startedAt === "number"
  );
}

function isCompletedReviewSession(value: unknown): value is CompletedReviewSession {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    v.version === SESSION_STORAGE_VERSION &&
    typeof v.sessionId === "string" &&
    typeof v.courseId === "string" &&
    isReviewScope(v.scope) &&
    (typeof v.chapterLabel === "string" || v.chapterLabel === null) &&
    typeof v.endedAt === "number" &&
    isNumberTally(v.gradedTally) &&
    isStringArray(v.againCardIds)
  );
}

export function readActiveReviewSession(): ActiveReviewSession | null {
  const parsed = readJson(ACTIVE_REVIEW_SESSION_STORAGE_KEY);
  return isActiveReviewSession(parsed) ? parsed : null;
}

export function writeActiveReviewSession(session: ActiveReviewSession): void {
  writeJson(ACTIVE_REVIEW_SESSION_STORAGE_KEY, session);
}

export function clearActiveReviewSession(): void {
  remove(ACTIVE_REVIEW_SESSION_STORAGE_KEY);
}

export function readCompletedReviewSession(): CompletedReviewSession | null {
  const parsed = readJson(COMPLETED_REVIEW_SESSION_STORAGE_KEY);
  if (!isCompletedReviewSession(parsed)) return null;
  if (Date.now() - parsed.endedAt >= COMPLETED_SESSION_TTL_MS) {
    clearCompletedReviewSession();
    return null;
  }
  return parsed;
}

export function writeCompletedReviewSession(session: CompletedReviewSession): void {
  writeJson(COMPLETED_REVIEW_SESSION_STORAGE_KEY, session);
}

export function clearCompletedReviewSession(): void {
  remove(COMPLETED_REVIEW_SESSION_STORAGE_KEY);
}
