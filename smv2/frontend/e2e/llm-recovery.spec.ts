import { expect, test } from "@playwright/test";

import {
  assertNoDisposableCourses,
  attachPageErrorGuard,
  cleanupDisposableCourses,
  createPdfCourse,
  deleteCourse,
  expectCleanPage,
  llm503Detail,
} from "./support/test-data";

test("structured lesson-start 503 keeps recovery clickable and opens Settings", async ({
  page,
  request,
}, testInfo) => {
  test.setTimeout(60_000);
  await cleanupDisposableCourses(request);
  const course = await createPdfCourse(request, testInfo);
  const errors = attachPageErrorGuard(page);

  try {
    await page.addInitScript(() => window.localStorage.clear());
    await page.route(`**/api/sections/${course.sectionId}/lesson**`, (route) => {
      if (route.request().method() === "POST") {
        return route.fulfill({ status: 503, json: llm503Detail("E2E provider is not ready") });
      }
      return route.continue();
    });

    await page.goto(`/course/${course.courseId}`);
    await page.getByRole("button", { name: "Lesson", exact: true }).click();
    const generate = page.getByRole("button", { name: "Generate lesson" });
    await expect(generate).toBeEnabled();
    await generate.click();

    await expect(page.getByText("E2E provider is not ready")).toBeVisible();
    const settingsLink = page.getByRole("link", { name: "Open Settings" });
    await expect(settingsLink).toBeVisible();
    await settingsLink.click();
    await expect(page).toHaveURL(/\/settings$/);
    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
    await expectCleanPage(
      errors.filter((error) => !error.includes("503 (Service Unavailable)")),
    );
  } finally {
    await deleteCourse(request, course.courseId);
    await cleanupDisposableCourses(request);
    await assertNoDisposableCourses(request);
  }
});
