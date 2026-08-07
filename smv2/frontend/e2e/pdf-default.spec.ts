import { expect, test } from "@playwright/test";

import {
  assertNoDisposableCourses,
  attachPageErrorGuard,
  cleanupDisposableCourses,
  createPdfCourse,
  deleteCourse,
  expectCleanPage,
} from "./support/test-data";

test("a newly opened uploaded PDF course defaults to Pages view", async ({ page, request }, testInfo) => {
  test.setTimeout(60_000);
  await cleanupDisposableCourses(request);
  const course = await createPdfCourse(request, testInfo);
  const errors = attachPageErrorGuard(page);

  try {
    await page.addInitScript(() => window.localStorage.clear());
    await page.goto(`/course/${course.courseId}`);

    await expect(page.getByRole("button", { name: "Pages", exact: true })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: "Source", exact: true })).toHaveAttribute("aria-pressed", "false");
    await expect(page.getByText("SourceMind E2E PDF course").first()).toBeVisible();
    await expectCleanPage(errors);
  } finally {
    await deleteCourse(request, course.courseId);
    await cleanupDisposableCourses(request);
    await assertNoDisposableCourses(request);
  }
});
