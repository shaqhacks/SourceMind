import { expect, test } from "@playwright/test";

import {
  assertNoDisposableCourses,
  attachPageErrorGuard,
  cleanupDisposableCourses,
  createPdfCourse,
  deleteCourse,
  expectCleanPage,
  mockedSettings,
} from "./support/test-data";

const routes = ["/", "/flashcards", "/jobs", "/review", "/search", "/settings", "/tests"];

test.describe("route shells and clickability", () => {
  test.beforeEach(async ({ request }) => {
    await cleanupDisposableCourses(request);
  });

  test.afterEach(async ({ request }) => {
    await cleanupDisposableCourses(request);
    await assertNoDisposableCourses(request);
  });

  for (const route of routes) {
    test(`renders and keeps shell controls clickable for ${route}`, async ({ page }) => {
      await page.route("**/api/settings", (route) => route.fulfill({ json: mockedSettings() }));
      const errors = attachPageErrorGuard(page);

      await page.goto(route);
      await expect(page.getByRole("main")).toHaveCount(1);
      if (route === "/search") {
        await expect(page.getByText("Add a course before searching your course text.")).toBeVisible();
      } else {
        await expect(page.getByRole("heading").first()).toBeVisible();
      }

      const navButton = page.getByRole("button", {
        name: /Open navigation|Close navigation|Collapse sidebar|Expand sidebar/,
      }).first();
      await expect(navButton).toBeVisible();
      await navButton.click();

      if (page.viewportSize()?.width === 390) {
        await expect(page.getByRole("dialog", { name: "App navigation" })).toBeVisible();
        await page.getByRole("button", { name: "Close navigation" }).click();
        await expect(page.getByRole("dialog", { name: "App navigation" })).toBeHidden();
      }

      await expectCleanPage(errors);
    });
  }
});

test.describe("390x844 mobile reader controls", () => {
  test("opens and closes outline, chat, and settings controls without blocked clicks", async ({
    page,
    request,
  }, testInfo) => {
    test.skip(testInfo.project.name !== "mobile-chromium", "mobile overlay coverage runs in the mobile project");
    test.setTimeout(60_000);
    await page.route("**/api/settings", (route) => route.fulfill({ json: mockedSettings() }));
    let readinessCheckCalls = 0;
    await page.route("**/api/llm/status/check", (route) => {
      if (route.request().method() !== "POST") return route.continue();
      readinessCheckCalls += 1;
      return route.fulfill({
        json: {
          provider: "ollama",
          model: "e2e-mobile-unavailable:latest",
          configured: true,
          available: false,
          capabilities: { completion: true, embeddings: true },
          last_checked_at: "2026-08-07T00:00:00Z",
          failure_category: "e2e_mobile_readiness_probe_blocked",
          remediation: "E2E deterministic readiness result.",
        },
      });
    });
    const course = await createPdfCourse(request, testInfo);
    const errors = attachPageErrorGuard(page);

    try {
      await page.addInitScript(() => window.localStorage.clear());
      await page.goto(`/course/${course.courseId}`);
      await expect(page.getByRole("button", { name: "Pages", exact: true })).toHaveAttribute("aria-pressed", "true");

      await page.getByRole("button", { name: "Show outline" }).click();
      await expect(page.getByRole("dialog", { name: "Chapter outline" })).toBeVisible();
      await page.getByRole("button", { name: "Close outline" }).click();
      await expect(page.getByRole("dialog", { name: "Chapter outline" })).toBeHidden();

      await page.getByRole("button", { name: "Open chat" }).click();
      const chatDialog = page.getByRole("dialog", { name: "Course chat" });
      await expect(chatDialog).toBeVisible();
      await chatDialog.getByRole("button", { name: "Close chat" }).click();
      await expect(page.getByRole("button", { name: "Open chat" })).toBeVisible();

      await page.goto("/settings");
      await page.getByLabel("Provider").selectOption("ollama");
      await expect(page.getByLabel("Model")).toBeVisible();
      await expect(page.getByRole("button", { name: "Test connection" })).toBeEnabled();
      await page.getByRole("button", { name: "Test connection" }).click();
      await expect(page.getByText("Connection unavailable.")).toBeVisible();
      await expect(page.getByText("E2E deterministic readiness result.")).toBeVisible();
      expect(readinessCheckCalls, "mobile settings test uses deterministic readiness route").toBe(1);

      await expectCleanPage(errors);
    } finally {
      await deleteCourse(request, course.courseId);
      await cleanupDisposableCourses(request);
      await assertNoDisposableCourses(request);
    }
  });
});
