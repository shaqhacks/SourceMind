import { expect, test, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

import { attachPageErrorGuard, expectCleanPage } from "./support/test-data";

type GenerationPhase = "loading" | "thinking" | "cancelled";

interface GenerationRouteOptions {
  phases: GenerationPhase[];
  elapsedSeconds?: number;
  cancelAccepted?: boolean;
}

const courseId = "course-streaming";
const practiceSectionId = "section-practice";
const jobId = "job-streaming";
const apiProviders = [
  "**://api.anthropic.com/**",
  "**://api.openai.com/**",
  "**://127.0.0.1:11434/**",
  "**://localhost:11434/**",
];

const chapter = {
  chapter_label: "Chapter 1",
  section_ids: ["section-content"],
  practice_section_ids: [practiceSectionId],
  answers_section_ids: [],
  test_stats: null,
};

const practiceSection = {
  id: practiceSectionId,
  course_id: courseId,
  title: "Practice Set",
  order_index: 2,
  page_start: 1,
  page_end: 1,
  kind: "practice",
  chapter_label: "Chapter 1",
  asset_id: null,
  body_md: "Practice prompt from the textbook.",
  content_hash: "hash-practice",
  lesson_md: null,
  lesson_status: "none",
  lesson_stale: false,
  lesson_model: null,
  lesson_prompt_version: null,
  extractor_version: null,
  created_at: "2026-08-07T00:00:00Z",
  updated_at: "2026-08-07T00:00:00Z",
};

const contentSection = {
  ...practiceSection,
  id: "section-content",
  title: "Source chapter",
  order_index: 1,
  kind: "content",
  body_md: "Source chapter body.",
};

const course = {
  id: courseId,
  title: "Streaming reliability course",
  status: "ready",
  source_type: "pdf",
  created_at: "2026-08-07T00:00:00Z",
  updated_at: "2026-08-07T00:00:00Z",
  asset_count: 1,
  failed_asset_count: 0,
};

const jobBase = {
  id: jobId,
  type: "generate_test",
  payload: { course_id: courseId, chapter_label: "Chapter 1" },
  result: null,
  error: null,
  error_detail: null,
  retryable: true,
  attempts: 0,
  cancel_requested_at: null,
  created_at: "2026-08-07T00:00:00Z",
  updated_at: "2026-08-07T00:00:00Z",
};

async function expectNoCriticalViolations(page: Page, name: string) {
  const results = await new AxeBuilder({ page }).include("body").analyze();
  const critical = results.violations.filter((violation) => violation.impact === "critical");
  test.info().annotations.push({
    type: `axe:${name}`,
    description: critical.map((violation) => `${violation.id}:${violation.nodes.length}`).join(", ") || "none",
  });
  expect(critical).toEqual([]);
}

async function installNoPaidProviderGuard(page: Page) {
  const calls: string[] = [];
  for (const pattern of apiProviders) {
    await page.route(pattern, (route) => {
      calls.push(route.request().url());
      return route.abort();
    });
  }
  return calls;
}

async function installFakeEventSource(page: Page, options: GenerationRouteOptions) {
  const elapsedSeconds = options.elapsedSeconds ?? 0;
  await page.addInitScript(
    ({ phases, elapsedSeconds }) => {
      class FakeGenerationEventSource extends EventTarget {
        static CONNECTING = 0;
        static OPEN = 1;
        static CLOSED = 2;
        readonly CONNECTING = 0;
        readonly OPEN = 1;
        readonly CLOSED = 2;
        readonly url: string;
        readonly withCredentials = false;
        readyState = 0;
        onopen: ((event: Event) => void) | null = null;
        onmessage: ((event: MessageEvent) => void) | null = null;
        onerror: ((event: Event) => void) | null = null;

        constructor(url: string | URL) {
          super();
          this.url = String(url);
          const globalWithSources = window as typeof window & {
            __smv2GenerationSources?: FakeGenerationEventSource[];
          };
          globalWithSources.__smv2GenerationSources = globalWithSources.__smv2GenerationSources ?? [];
          globalWithSources.__smv2GenerationSources.push(this);
          window.setTimeout(() => {
            if (this.readyState === this.CLOSED) return;
            this.readyState = this.OPEN;
            const open = new Event("open");
            this.onopen?.(open);
            this.dispatchEvent(open);
            phases.filter((phase) => phase !== "cancelled").forEach((phase, index) => {
              window.setTimeout(() => this.emit(phase), index * 5);
            });
          }, 0);
        }

        close() {
          this.readyState = this.CLOSED;
        }

        private emit(phase: string) {
          if (this.readyState === this.CLOSED) return;
          const status = phase === "cancelled" ? "cancelled" : "running";
          const data = {
            id: "job-streaming",
            status,
            progress:
              phase === "cancelled"
                ? null
                : {
                    stage: phase,
                    pct: phase === "loading" ? 10 : 45,
                    message: "Deterministic local generation progress.",
                    elapsed_seconds: elapsedSeconds,
                    last_activity_seconds: 0,
                  },
          };
          const event = new MessageEvent("update", { data: JSON.stringify(data) });
          this.dispatchEvent(event);
          if (status === "cancelled") this.close();
        }
      }

      window.EventSource = FakeGenerationEventSource as unknown as typeof EventSource;
      const originalFetch = window.fetch.bind(window);
      window.fetch = async (...args) => {
        const response = await originalFetch(...args);
        const input = args[0];
        const url = typeof input === "string" ? input : input instanceof Request ? input.url : String(input);
        if (url.includes("/api/jobs/job-streaming/cancel")) {
          window.setTimeout(() => {
            const globalWithSources = window as typeof window & {
              __smv2GenerationSources?: Array<{ emit: (phase: string) => void }>;
            };
            for (const source of globalWithSources.__smv2GenerationSources ?? []) {
              source.emit("cancelled");
            }
          }, 0);
        }
        return response;
      };
    },
    { phases: options.phases, elapsedSeconds },
  );
}

async function installChapterRoutes(page: Page) {
  await page.route(`**/api/courses/${courseId}/chapters**`, (route) =>
    route.fulfill({ json: [chapter] }),
  );
  await page.route("**/api/sections/**", (route) => {
    const sectionId = route.request().url().split("/api/sections/")[1]?.split(/[?#]/)[0];
    return route.fulfill({ json: sectionId === "section-content" ? contentSection : practiceSection });
  });
  await page.route(`**/api/courses/${courseId}/tests**`, (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({ status: 202, json: { job_id: jobId } });
    }
    return route.fulfill({ json: [] });
  });
  await page.route(new RegExp(`/api/jobs/${jobId}/cancel(?:[?#].*)?$`), (route) =>
    route.fulfill({
      json: {
        ...jobBase,
        status: "cancelled",
        cancel_requested_at: "2026-08-07T00:00:01Z",
      },
    }),
  );
  await page.route(new RegExp(`/api/jobs/${jobId}(?:[?#].*)?$`), (route) =>
    route.fulfill({ json: { ...jobBase, status: "running", progress: null } }),
  );
  await page.route(`**/api/courses/${courseId}/sections**`, (route) => {
    return route.fulfill({ json: [contentSection] });
  });
  await page.route(`**/api/courses/${courseId}/progress**`, (route) => {
    return route.fulfill({ json: { section_id: "section-content", scroll_pos: 0 } });
  });
  await page.route(new RegExp(`/api/courses/${courseId}(?:[?#].*)?$`), (route) => {
    return route.fulfill({ json: course });
  });
}

async function installReaderRoutes(page: Page) {
  await page.route(`**/api/sections/section-content/cards**`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/courses/${courseId}/highlights**`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route(`**/api/courses/${courseId}/notes**`, (route) =>
    route.fulfill({ json: [] }),
  );
  await page.route("**/api/llm/usage**", (route) =>
    route.fulfill({ json: { calls: 0, est_cost_usd: 0 } }),
  );
  await page.route("**/api/jobs", (route) => route.fulfill({ json: [] }));
}

async function installGenerationRoutes(page: Page, options: GenerationRouteOptions) {
  await installFakeEventSource(page, options);
  await installChapterRoutes(page);
  await installReaderRoutes(page);
  await page.route(`**/api/courses/${courseId}/sections/${practiceSectionId}/practice-assessment**`, (route) =>
    route.fulfill({
      json: {
        section_id: practiceSectionId,
        status: "ready",
        questions: [],
        job_id: null,
        message: null,
        run_id: "practice-ready",
      },
    }),
  );
}

async function installPracticeFailureRoute(page: Page, { code }: { code: "invalid_model_output" }) {
  await installChapterRoutes(page);
  await page.route(`**/api/courses/${courseId}/sections/${practiceSectionId}/practice-assessment**`, (route) => {
    if (route.request().method() === "POST") {
      return route.fulfill({
        status: 503,
        json: {
          detail: {
            code,
            failure_category: "structured_output_invalid",
            message: "The model returned invalid practice questions. Retry generation.",
            remediation: "Retry practice generation; persistent failures are visible from Jobs.",
          },
        },
      });
    }
    return route.fulfill({
      json: {
        section_id: practiceSectionId,
        status: "not_started",
        questions: undefined,
        job_id: null,
        message: null,
        run_id: null,
      },
    });
  });
}

async function openChapterPractice(page: Page) {
  await page.goto(`/course/${courseId}/chapter/Chapter%201/test`);
  await expect(page.getByRole("heading", { name: "Chapter 1 — Chapter test" })).toBeVisible({ timeout: 15_000 });
}

async function expectNoRawProviderOutput(page: Page) {
  await expect(page.locator("body")).not.toContainText(/<think>|raw provider|api\.anthropic|claude|openai/i);
}

function appAlerts(page: Page) {
  return page.locator('[role="alert"]:not(#__next-route-announcer__)');
}

async function expectCleanGenerationPage(errors: string[], allowed: RegExp[] = []) {
  await expectCleanPage(
    errors.filter(
      (error) =>
        !error.includes("/_next/hmr") &&
        !error.includes("ERR_INVALID_HTTP_RESPONSE") &&
        !allowed.some((pattern) => pattern.test(error)),
    ),
  );
}

async function expectThinkingLivenessAndBackgroundAction(page: Page) {
  await openChapterPractice(page);
  await page.getByRole("button", { name: "Take chapter test" }).click();

  await expect(page.getByText("Thinking · 2m 05s")).toBeVisible();
  await expect(
    page.getByText("This can take a little while. You can keep studying while generation continues."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue in background" })).toBeEnabled();
  await expect(appAlerts(page)).toHaveCount(0);

  await expectNoCriticalViolations(page, "thinking-background");
  await expectNoRawProviderOutput(page);

  await page.getByRole("button", { name: "Continue in background" }).click();
  await expect(page).toHaveURL(new RegExp(`/course/${courseId}$`));
}

async function expectCancellationWithoutFailure(page: Page) {
  await openChapterPractice(page);
  await page.getByRole("button", { name: "Take chapter test" }).click();

  await expect(page.getByText("Thinking · 0s")).toBeVisible();
  await page.getByRole("button", { name: "Cancel generation" }).click();
  await expect(page.getByRole("button", { name: "Take chapter test" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Cancel generation" })).toHaveCount(0);
  await expect(appAlerts(page)).toHaveCount(0);
  await expect(page.getByText(/Generation failed/i)).toHaveCount(0);

  await expectNoCriticalViolations(page, "cancelled-terminal");
  await expectNoRawProviderOutput(page);
}

async function expectStructuredRetryGuidance(page: Page) {
  await openChapterPractice(page);

  const banner = appAlerts(page);
  await expect(banner).toContainText("The model returned invalid practice questions. Retry generation.");
  await expect(banner.getByRole("button", { name: "Retry" })).toBeVisible();
  await expect(page.getByRole("link", { name: "View job details" })).toHaveAttribute("href", "/jobs");

  await expectNoCriticalViolations(page, "invalid-practice-output");
  await expectNoRawProviderOutput(page);
}

test("thinking remains active beyond the old timeout and can continue in background", async ({
  page,
}) => {
  const paidProviderCalls = await installNoPaidProviderGuard(page);
  const errors = attachPageErrorGuard(page);

  await installGenerationRoutes(page, { phases: ["loading", "thinking"], elapsedSeconds: 125 });
  await expectThinkingLivenessAndBackgroundAction(page);

  expect(paidProviderCalls, "browser made no paid provider calls").toEqual([]);
  await expectCleanGenerationPage(errors);
});

test("cancelled generation becomes terminal without a failure banner", async ({ page }) => {
  const paidProviderCalls = await installNoPaidProviderGuard(page);
  const errors = attachPageErrorGuard(page);

  await installGenerationRoutes(page, { phases: ["thinking", "cancelled"], cancelAccepted: true });
  await expectCancellationWithoutFailure(page);

  expect(paidProviderCalls, "browser made no paid provider calls").toEqual([]);
  await expectCleanGenerationPage(errors);
});

test("invalid practice output surfaces structured retry guidance", async ({ page }) => {
  const paidProviderCalls = await installNoPaidProviderGuard(page);
  const errors = attachPageErrorGuard(page);

  await installPracticeFailureRoute(page, { code: "invalid_model_output" });
  await expectStructuredRetryGuidance(page);

  expect(paidProviderCalls, "browser made no paid provider calls").toEqual([]);
  await expectCleanGenerationPage(errors, [/503 \(Service Unavailable\)/]);
});
