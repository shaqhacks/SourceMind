import { describe, expect, it } from "vitest";

import type { CourseOut } from "@/lib/api/client";
import { percentComplete, pickMostRecentCourse } from "@/lib/dashboard/continue";

function makeCourse(overrides: Partial<CourseOut> = {}): CourseOut {
  return {
    id: "course-1",
    title: "Course",
    status: "ready",
    section_count: 4,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    progress: null,
    ...overrides,
  };
}

describe("pickMostRecentCourse", () => {
  it("returns null when there are no courses", () => {
    expect(pickMostRecentCourse([])).toBeNull();
  });

  it("returns null when no course has any saved progress", () => {
    const courses = [makeCourse({ id: "a" }), makeCourse({ id: "b" })];
    expect(pickMostRecentCourse(courses)).toBeNull();
  });

  it("ignores a course whose progress has a null section_id or updated_at", () => {
    const courses = [
      makeCourse({
        id: "a",
        progress: { section_id: null, scroll_pos: 0, updated_at: "2026-01-05T00:00:00Z" },
      }),
      makeCourse({
        id: "b",
        progress: { section_id: "sec-1", scroll_pos: 0.2, updated_at: null },
      }),
    ];
    expect(pickMostRecentCourse(courses)).toBeNull();
  });

  it("picks the course with the most recently updated progress", () => {
    const older = makeCourse({
      id: "older",
      progress: { section_id: "sec-1", scroll_pos: 0.1, updated_at: "2026-01-01T00:00:00Z" },
    });
    const newer = makeCourse({
      id: "newer",
      progress: { section_id: "sec-2", scroll_pos: 0.4, updated_at: "2026-01-10T00:00:00Z" },
    });
    expect(pickMostRecentCourse([older, newer])).toBe(newer);
    expect(pickMostRecentCourse([newer, older])).toBe(newer);
  });
});

describe("percentComplete", () => {
  it("computes 1-based chapter position as a percentage", () => {
    expect(percentComplete(0, 4)).toBe(25);
    expect(percentComplete(1, 4)).toBe(50);
    expect(percentComplete(3, 4)).toBe(100);
  });

  it("returns 0 for a course with no sections, instead of dividing by zero", () => {
    expect(percentComplete(0, 0)).toBe(0);
  });
});
