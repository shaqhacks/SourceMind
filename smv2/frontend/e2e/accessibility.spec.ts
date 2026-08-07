import { expect, test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

import {
  assertNoDisposableCourses,
  cleanupDisposableCourses,
  createPdfCourse,
  deleteCourse,
  mockedSettings,
} from "./support/test-data";

const shellRoutes = ["/", "/flashcards", "/jobs", "/review", "/search", "/settings", "/tests"];

async function expectNoCriticalViolations(page: import("@playwright/test").Page, name: string) {
  const results = await new AxeBuilder({ page }).include("main").analyze();
  const critical = results.violations.filter((violation) => violation.impact === "critical");
  const nonCritical = results.violations.filter((violation) => violation.impact !== "critical");
  test.info().annotations.push({
    type: `axe:${name}:serious-moderate`,
    description: nonCritical
      .filter((violation) => violation.impact === "serious" || violation.impact === "moderate")
      .map((violation) => `${violation.id}:${violation.nodes.length}`)
      .join(", ") || "none",
  });
  expect(critical).toEqual([]);
}

test.describe("critical axe coverage", () => {
  test.beforeEach(async ({ request }) => {
    await cleanupDisposableCourses(request);
  });

  test.afterEach(async ({ request }) => {
    await cleanupDisposableCourses(request);
    await assertNoDisposableCourses(request);
  });

  for (const route of shellRoutes) {
    test(`has no critical axe violations on ${route}`, async ({ page }) => {
      await page.route("**/api/settings", (route) => route.fulfill({ json: mockedSettings() }));
      await page.goto(route);
      await expect(page.getByRole("main")).toBeVisible();
      if (route === "/search") {
        await expect(page.getByText("Add a course before searching your course text.")).toBeVisible();
      } else {
        await expect(page.getByRole("heading").first()).toBeVisible();
      }
      await expectNoCriticalViolations(page, route);
    });
  }

  test("has no critical axe violations on a representative course reader", async ({
    page,
    request,
  }, testInfo) => {
    test.setTimeout(60_000);
    const course = await createPdfCourse(request, testInfo);
    try {
      await page.addInitScript(() => window.localStorage.clear());
      await page.goto(`/course/${course.courseId}`);
      await expect(page.getByRole("button", { name: "Pages", exact: true })).toHaveAttribute("aria-pressed", "true");
      await expectNoCriticalViolations(page, "course-reader");
    } finally {
      await deleteCourse(request, course.courseId);
      await cleanupDisposableCourses(request);
      await assertNoDisposableCourses(request);
    }
  });
});
