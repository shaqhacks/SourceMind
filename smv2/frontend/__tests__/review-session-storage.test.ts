import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ACTIVE_REVIEW_SESSION_STORAGE_KEY,
  COMPLETED_REVIEW_SESSION_STORAGE_KEY,
  clearActiveReviewSession,
  clearCompletedReviewSession,
  readActiveReviewSession,
  readCompletedReviewSession,
  writeActiveReviewSession,
  writeCompletedReviewSession,
  type ActiveReviewSession,
  type CompletedReviewSession,
} from "@/lib/review/sessionStorage";

const now = 1_800_000_000_000;

function activeSession(overrides: Partial<ActiveReviewSession> = {}): ActiveReviewSession {
  return {
    version: 1,
    sessionId: "active-session",
    courseId: "course-1",
    scope: "available",
    chapterLabel: null,
    chosenSize: 3,
    remainingCardIds: ["card-1", "card-2"],
    gradedTally: { 3: 1 },
    againCardIds: [],
    startedAt: now - 10_000,
    ...overrides,
  };
}

function completedSession(overrides: Partial<CompletedReviewSession> = {}): CompletedReviewSession {
  return {
    version: 1,
    sessionId: "completed-session",
    courseId: "course-1",
    scope: "all",
    chapterLabel: "Chapter 1",
    endedAt: now,
    gradedTally: { 1: 2, 3: 1 },
    againCardIds: ["card-3", "card-1"],
    ...overrides,
  };
}

describe("review session storage", () => {
  afterEach(() => {
    localStorage.clear();
    vi.useRealTimers();
  });

  it("round-trips versioned active sessions with scope and chapter label", () => {
    const session = activeSession({ scope: "needs_attention", chapterLabel: "Chapter 2" });

    writeActiveReviewSession(session);

    expect(readActiveReviewSession()).toEqual(session);
    clearActiveReviewSession();
    expect(readActiveReviewSession()).toBeNull();
  });

  it("ignores malformed active storage and unknown active versions", () => {
    localStorage.setItem(ACTIVE_REVIEW_SESSION_STORAGE_KEY, "{bad json");
    expect(readActiveReviewSession()).toBeNull();

    localStorage.setItem(
      ACTIVE_REVIEW_SESSION_STORAGE_KEY,
      JSON.stringify({ ...activeSession(), version: 999 }),
    );

    expect(readActiveReviewSession()).toBeNull();
  });

  it("round-trips completed snapshots without card content, including an empty Again list", () => {
    const session = completedSession({ againCardIds: [] });

    writeCompletedReviewSession(session);

    const raw = localStorage.getItem(COMPLETED_REVIEW_SESSION_STORAGE_KEY);
    expect(raw).not.toContain("front_md");
    expect(raw).not.toContain("back_md");
    expect(readCompletedReviewSession()).toEqual(session);
    clearCompletedReviewSession();
    expect(readCompletedReviewSession()).toBeNull();
  });

  it("ignores malformed completed storage and unknown completed versions", () => {
    localStorage.setItem(COMPLETED_REVIEW_SESSION_STORAGE_KEY, "{bad json");
    expect(readCompletedReviewSession()).toBeNull();

    localStorage.setItem(
      COMPLETED_REVIEW_SESSION_STORAGE_KEY,
      JSON.stringify({ ...completedSession(), version: 999 }),
    );

    expect(readCompletedReviewSession()).toBeNull();
  });

  it("expires completed snapshots at 24 hours", () => {
    vi.setSystemTime(now);
    vi.useFakeTimers();
    writeCompletedReviewSession(completedSession({ endedAt: now - 86_400_000 + 1 }));
    expect(readCompletedReviewSession()).not.toBeNull();

    writeCompletedReviewSession(completedSession({ endedAt: now - 86_400_000 }));

    expect(readCompletedReviewSession()).toBeNull();
    expect(localStorage.getItem(COMPLETED_REVIEW_SESSION_STORAGE_KEY)).toBeNull();
  });
});
