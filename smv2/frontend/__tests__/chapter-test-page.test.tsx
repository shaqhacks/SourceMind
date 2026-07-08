import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ChapterTestPage from "@/app/course/[courseId]/chapter/[chapterLabel]/test/page";

vi.mock("@/components/chapter/ChapterTestClient", () => ({
  default: ({ courseId, chapterLabel }: { courseId: string; chapterLabel: string }) => (
    <div data-testid="chapter-test-client" data-course-id={courseId} data-chapter-label={chapterLabel} />
  ),
}));

describe("ChapterTestPage", () => {
  it("decodes the chapter label route segment before rendering the client", async () => {
    const element = await ChapterTestPage({
      params: Promise.resolve({
        courseId: "course-1",
        chapterLabel: "Chapter%203%20%3A%20Inequalities",
      }),
    });

    render(element);

    expect(screen.getByTestId("chapter-test-client")).toHaveAttribute(
      "data-chapter-label",
      "Chapter 3 : Inequalities",
    );
  });

  it("leaves malformed percent escapes unchanged instead of crashing the route", async () => {
    const element = await ChapterTestPage({
      params: Promise.resolve({
        courseId: "course-1",
        chapterLabel: "Chapter%ZZ",
      }),
    });

    render(element);

    expect(screen.getByTestId("chapter-test-client")).toHaveAttribute(
      "data-chapter-label",
      "Chapter%ZZ",
    );
  });
});
