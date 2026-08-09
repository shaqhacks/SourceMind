import AxeBuilder from "@axe-core/playwright";
import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";

type AssessmentStatus = "ready" | "generating" | "failed" | "not_started";

interface BrowserError {
  kind: "console" | "pageerror";
  text: string;
  url?: string;
}

interface PracticePost {
  sectionId: string;
  url: string;
}

interface PracticeGet {
  body: unknown;
  sectionId: string;
}

interface TestPost {
  body: unknown;
  url: string;
}

const courseId = "course-chapter-practice-recovery";
const chapterLabel = "Chapter 4: Mixed State";
const encodedChapterLabel = encodeURIComponent(chapterLabel);
const contentSectionId = "section-chapter-4-content";
const readySectionId = "practice-ready";
const generatingSectionId = "practice-generating";
const failedSectionId = "practice-failed";
const invalidSectionId = "practice-invalid";
const settingsSectionId = "practice-settings";
const generatedJobId = "job-chapter-test-ready";
const generatedAttemptId = "attempt-generated-mixed-state";
const rawInvalidOutputSentinel =
  "RAW_PRIVATE_PARSER_PROVIDER_SENTINEL parser stack raw provider api.openai.com <think>";

const paidProviderPatterns = [
  "**://api.anthropic.com/**",
  "**://api.openai.com/**",
  "**://127.0.0.1:11434/**",
  "**://localhost:11434/**",
];

const now = "2026-08-09T12:00:00Z";

function attachBrowserErrorGuard(page: Page) {
  const errors: BrowserError[] = [];
  page.on("pageerror", (error) => errors.push({ kind: "pageerror", text: error.message }));
  page.on("console", (message: ConsoleMessage) => {
    if (message.type() !== "error") return;
    errors.push({
      kind: "console",
      text: message.text(),
      url: message.location().url,
    });
  });
  return errors;
}

async function installProviderGuard(page: Page) {
  const calls: string[] = [];
  for (const pattern of paidProviderPatterns) {
    await page.route(pattern, (route) => {
      calls.push(route.request().url());
      return route.abort();
    });
  }
  return calls;
}

async function expectNoCriticalViolations(page: Page, label: string) {
  const results = await new AxeBuilder({ page }).include("body").analyze();
  const critical = results.violations.filter((violation) => violation.impact === "critical");
  test.info().annotations.push({
    type: `axe:${label}`,
    description:
      critical.map((violation) => `${violation.id}:${violation.nodes.length}`).join(", ") ||
      "none",
  });
  expect(critical).toEqual([]);
}

async function installFakeEventSource(page: Page) {
  await page.addInitScript(
    ({ generatedJobId }) => {
      class FakeJobEventSource extends EventTarget {
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
          window.setTimeout(() => {
            if (this.readyState === this.CLOSED) return;
            this.readyState = this.OPEN;
            const open = new Event("open");
            this.onopen?.(open);
            this.dispatchEvent(open);
            window.setTimeout(() => this.emit("running"), 5);
          }, 0);
        }

        close() {
          this.readyState = this.CLOSED;
        }

        private emit(status: "running") {
          if (this.readyState === this.CLOSED || !this.url.includes(generatedJobId)) return;
          const event = new MessageEvent("update", {
            data: JSON.stringify({
              id: generatedJobId,
              status,
              progress: {
                stage: "thinking",
                pct: 40,
                message: "Deterministic chapter-test generation.",
                elapsed_seconds: 6,
                last_activity_seconds: 0,
              },
            }),
          });
          this.dispatchEvent(event);
        }
      }

      window.EventSource = FakeJobEventSource as unknown as typeof EventSource;
    },
    { generatedJobId },
  );
}

function chapter() {
  return {
    chapter_label: chapterLabel,
    section_ids: [contentSectionId],
    practice_section_ids: [readySectionId, generatingSectionId, failedSectionId],
    answers_section_ids: [],
    test_stats: null,
  };
}

function section(id: string) {
  return {
    id,
    course_id: courseId,
    title: `Practice source ${id}`,
    order_index: id === contentSectionId ? 1 : 2,
    page_start: 12,
    page_end: 13,
    kind: id === contentSectionId ? "content" : "practice",
    chapter_label: chapterLabel,
    asset_id: null,
    body_md: `Source text for ${id}.`,
    content_hash: `hash-${id}`,
    lesson_md: null,
    lesson_status: "none",
    lesson_stale: false,
    lesson_model: null,
    lesson_prompt_version: null,
    extractor_version: null,
    created_at: now,
    updated_at: now,
  };
}

function question(sectionId: string, number = "1") {
  return {
    id: `question-${sectionId}-${number}`,
    problem_number: number,
    source_ref: "p. 12",
    stem_md: `What does ${sectionId} ask you to solve?`,
    choices: ["A worked answer", "A distractor", "Another distractor"],
    concept: { id: `concept-${sectionId}`, label: "Mixed-state practice", slug: "mixed-state" },
    answered: null,
  };
}

function assessment(sectionId: string, status: AssessmentStatus, overrides = {}) {
  return {
    section_id: sectionId,
    status,
    questions: status === "ready" ? [question(sectionId)] : [],
    job_id: status === "generating" ? `job-${sectionId}` : null,
    message: status === "generating" ? "Preparing practice questions." : null,
    run_id: status === "ready" ? `run-${sectionId}` : null,
    ...overrides,
  };
}

function invalidModelFailure(sectionId: string) {
  return assessment(sectionId, "failed", {
    message: "The model returned invalid practice questions. Retry generation.",
    error_detail: {
      code: "invalid_model_output",
      failure_category: "structured_output_invalid",
      message: "The model returned invalid practice questions. Retry generation.",
      remediation: "Retry practice generation; persistent failures are visible from Jobs.",
      parser_debug: rawInvalidOutputSentinel,
      raw_provider_output: {
        provider: "openai",
        text: rawInvalidOutputSentinel,
      },
    },
  });
}

function missingOllamaFailure(sectionId: string) {
  return assessment(sectionId, "failed", {
    message: "Your configured Ollama model is not installed.",
    error_detail: {
      code: "llm_readiness_unavailable",
      failure_category: "ollama_model_unavailable",
      message: "Your configured Ollama model is not installed.",
      remediation: "Open Settings and select a currently installed model.",
    },
  });
}

function testSummary() {
  return {
    id: "test-generated-mixed-state",
    course_id: courseId,
    chapter_label: chapterLabel,
    question_count: 5,
    created_at: now,
    attempts: [{ id: generatedAttemptId, created_at: now, score: null }],
  };
}

async function installChapterRoutes(
  page: Page,
  options: {
    states: Record<string, ReturnType<typeof assessment>>;
    onPracticePost?: (sectionId: string, attempt: number) => ReturnType<typeof assessment>;
    onTestPost?: () => void;
    practiceSectionIds?: string[];
    initialTests?: unknown[];
    generatedTests?: unknown[];
  },
) {
  const practicePosts: PracticePost[] = [];
  const practiceGets: PracticeGet[] = [];
  const testPosts: TestPost[] = [];
  const getCounts = new Map<string, number>();
  const postCounts = new Map<string, number>();
  let testsGenerated = false;
  const practiceSectionIds = options.practiceSectionIds ?? [
    readySectionId,
    generatingSectionId,
    failedSectionId,
  ];

  await page.route("**/api/**", (route) =>
    route.fulfill({
      status: 599,
      json: { detail: `Unhandled E2E API route: ${route.request().method()} ${route.request().url()}` },
    }),
  );
  await page.route(`**/api/courses/${courseId}/chapters**`, (route) =>
    route.fulfill({
      json: [{ ...chapter(), practice_section_ids: practiceSectionIds }],
    }),
  );
  await page.route("**/api/review/summary", (route) =>
    route.fulfill({
      json: { due_total: 0, daily_throughput: 20, backlog_warning: false, courses: [] },
    }),
  );
  await page.route("**/api/courses", (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    return route.fulfill({
      json: [
        {
          id: courseId,
          title: "Chapter practice recovery",
          status: "ready",
          source_type: "pdf",
          created_at: now,
          updated_at: now,
          asset_count: 1,
          failed_asset_count: 0,
        },
      ],
    });
  });
  await page.route("**/api/llm/usage**", (route) =>
    route.fulfill({ json: { calls: 0, input_tokens: 0, output_tokens: 0, est_cost_usd: 0 } }),
  );
  await page.route("**/api/settings/bootstrap", (route) =>
    route.fulfill({ json: { csrf_token: "e2e-csrf-token", rollout: { local_settings_enabled: true } } }),
  );
  await page.route("**/api/settings", (route) =>
    route.fulfill({
      json: {
        provider: "ollama",
        model: "missing-model:latest",
        credentials_present: { anthropic: false, ollama: true },
        credentials: {},
        rollout: { local_settings_enabled: true },
        readiness: {
          provider: "ollama",
          model: "missing-model:latest",
          configured: true,
          available: false,
          capabilities: { completion: true, embeddings: true },
          last_checked_at: null,
          failure_category: "ollama_model_unavailable",
          remediation: "Select an installed Ollama model.",
        },
      },
    }),
  );
  await page.route("**/api/settings/ollama/models", (route) =>
    route.fulfill({
      json: {
        models: ["llama3.2:latest"],
        configured_model: "missing-model:latest",
        configured_model_available: false,
      },
    }),
  );
  await page.route("**/api/sections/**", (route) => {
    const sectionId = route.request().url().split("/api/sections/")[1]?.split(/[?#]/)[0];
    return route.fulfill({ json: section(sectionId ?? "unknown-section") });
  });
  await page.route(`**/api/courses/${courseId}/tests**`, async (route) => {
    if (route.request().method() === "POST") {
      testPosts.push({ url: route.request().url(), body: route.request().postDataJSON() });
      options.onTestPost?.();
      testsGenerated = true;
      return route.fulfill({ status: 202, json: { job_id: generatedJobId } });
    }
    return route.fulfill({
      json: testsGenerated ? (options.generatedTests ?? [testSummary()]) : (options.initialTests ?? []),
    });
  });
  await page.route(new RegExp(`/api/jobs/${generatedJobId}(?:[?#].*)?$`), (route) =>
    route.fulfill({
      json: {
        id: generatedJobId,
        type: "generate_test",
        payload: { course_id: courseId, chapter_label: chapterLabel },
        status: "running",
        progress: null,
        result: null,
        error: null,
        error_detail: null,
        retryable: true,
        attempts: 0,
        cancel_requested_at: null,
        created_at: now,
        updated_at: now,
      },
    }),
  );

  for (const sectionId of practiceSectionIds) {
    await page.route(
      `**/api/courses/${courseId}/sections/${sectionId}/practice-assessment**`,
      (route) => {
        if (route.request().method() === "POST") {
          const nextAttempt = (postCounts.get(sectionId) ?? 0) + 1;
          postCounts.set(sectionId, nextAttempt);
          practicePosts.push({ sectionId, url: route.request().url() });
          return route.fulfill({
            status: 202,
            json: options.onPracticePost?.(sectionId, nextAttempt) ?? assessment(sectionId, "ready"),
          });
        }

        const nextGet = (getCounts.get(sectionId) ?? 0) + 1;
        getCounts.set(sectionId, nextGet);
        const body = options.states[sectionId] ?? assessment(sectionId, "ready");
        practiceGets.push({ body, sectionId });
        return route.fulfill({
          json: body,
        });
      },
    );
  }

  return { practiceGets, practicePosts, testPosts };
}

async function openChapterTest(page: Page) {
  await page.goto(`/course/${courseId}/chapter/${encodedChapterLabel}/test`);
  await expect(
    page.getByRole("heading", { name: `${chapterLabel} — Chapter test` }),
  ).toBeVisible({ timeout: 15_000 });
}

function visibleAlerts(page: Page) {
  return page.locator('[role="alert"]:not(#__next-route-announcer__)');
}

async function expectNoPrivateOutput(page: Page) {
  await expect(page.locator("body")).not.toContainText(rawInvalidOutputSentinel);
  await expect(page.locator("body")).not.toContainText(
    /parser|traceback|stack|raw provider|raw model|<think>|api\.openai|api\.anthropic|claude/i,
  );
}

async function preparePage(page: Page) {
  const paidProviderCalls = await installProviderGuard(page);
  const browserErrors = attachBrowserErrorGuard(page);
  await installFakeEventSource(page);
  return { paidProviderCalls, browserErrors };
}

async function expectCleanGuards({
  paidProviderCalls,
  browserErrors,
}: {
  paidProviderCalls: string[];
  browserErrors: BrowserError[];
}) {
  expect(paidProviderCalls, "browser made no paid-provider or Ollama calls").toEqual([]);
  expect(browserErrors, "no uncaught page errors or console errors").toEqual([]);
}

async function runPartialReadiness({ page }: { page: Page }) {
  const guards = await preparePage(page);
  const posts = await installChapterRoutes(page, {
    states: {
      [readySectionId]: assessment(readySectionId, "ready"),
      [generatingSectionId]: assessment(generatingSectionId, "generating"),
      [failedSectionId]: invalidModelFailure(failedSectionId),
    },
  });

  await openChapterTest(page);
  await expect(page.getByRole("status", { name: "Practice readiness" })).toHaveText(
    "1 of 3 ready · 1 preparing · 1 needs retry",
  );
  await expect(page.getByText(`What does ${readySectionId} ask you to solve?`)).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue with ready (1)" })).toBeEnabled();
  await page.keyboard.press("Tab");
  await page.getByRole("button", { name: "Continue with ready (1)" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Practice section 1" })).toBeFocused();
  await expectNoCriticalViolations(page, "partial-readiness");
  await expectNoPrivateOutput(page);
  expect(posts.practicePosts.map((post) => post.sectionId)).toEqual([]);
  await expectCleanGuards(guards);
}

async function runSelectiveRetry({ page }: { page: Page }) {
  const guards = await preparePage(page);
  const posts = await installChapterRoutes(page, {
    states: {
      [readySectionId]: assessment(readySectionId, "ready"),
      [generatingSectionId]: assessment(generatingSectionId, "generating"),
      [failedSectionId]: invalidModelFailure(failedSectionId),
    },
    onPracticePost: (sectionId) => assessment(sectionId, "ready"),
  });

  await openChapterTest(page);
  await expect(page.getByRole("button", { name: "Retry failed (1)" })).toBeEnabled();
  await page.getByRole("button", { name: "Retry failed (1)" }).click();

  await expect(page.getByText(`What does ${failedSectionId} ask you to solve?`)).toBeVisible();
  await expect(page.getByRole("status", { name: "Practice readiness" })).toHaveText(
    "2 of 3 ready · 1 preparing",
  );
  expect(posts.practicePosts.map((post) => post.sectionId)).toEqual([failedSectionId]);
  expect(posts.practicePosts).toHaveLength(1);
  await expectNoCriticalViolations(page, "selective-retry");
  await expectNoPrivateOutput(page);
  await expectCleanGuards(guards);
}

async function runInvalidOutputRecovery({ page }: { page: Page }) {
  const guards = await preparePage(page);
  const posts = await installChapterRoutes(page, {
    practiceSectionIds: [invalidSectionId],
    states: {
      [invalidSectionId]: invalidModelFailure(invalidSectionId),
    },
    onPracticePost: (sectionId) => assessment(sectionId, "ready"),
  });

  await openChapterTest(page);
  await expect(visibleAlerts(page)).toContainText(
    "The model returned invalid practice questions. Retry generation.",
  );
  await expect(page.getByText("1 section needs a valid model response")).toBeVisible();
  await expect(page.getByRole("link", { name: "View job details" })).toHaveAttribute(
    "href",
    "/jobs",
  );
  expect(
    JSON.stringify(posts.practiceGets),
    "invalid-output mocked API response included the private raw sentinel",
  ).toContain(rawInvalidOutputSentinel);
  await expectNoPrivateOutput(page);
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByText(`What does ${invalidSectionId} ask you to solve?`)).toBeVisible();
  expect(posts.practicePosts.map((post) => post.sectionId)).toEqual([invalidSectionId]);
  expect(posts.practicePosts).toHaveLength(1);
  await expectNoCriticalViolations(page, "invalid-output-recovery");
  await expectCleanGuards(guards);
}

async function runMissingModelRecovery({ page }: { page: Page }) {
  const guards = await preparePage(page);
  const posts = await installChapterRoutes(page, {
    practiceSectionIds: [settingsSectionId],
    states: {
      [settingsSectionId]: missingOllamaFailure(settingsSectionId),
    },
  });

  await openChapterTest(page);
  await expect(visibleAlerts(page)).toContainText("Your configured Ollama model is not installed.");
  await expect(page.getByText("1 section needs model settings")).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry", exact: true })).toHaveCount(0);
  const settingsLink = page.getByRole("link", { name: "Open Settings" });
  await expect(settingsLink).toHaveAttribute("href", "/settings");
  await settingsLink.click();
  await expect(page).toHaveURL(/\/settings$/);
  expect(posts.practicePosts.map((post) => post.sectionId)).toEqual([]);
  await expectNoCriticalViolations(page, "missing-model-recovery");
  await expectCleanGuards(guards);
}

async function runIndependentTestGeneration({ page }: { page: Page }) {
  const guards = await preparePage(page);
  const posts = await installChapterRoutes(page, {
    states: {
      [readySectionId]: assessment(readySectionId, "ready"),
      [generatingSectionId]: assessment(generatingSectionId, "generating"),
      [failedSectionId]: invalidModelFailure(failedSectionId),
    },
  });

  await openChapterTest(page);
  await expect(page.getByRole("status", { name: "Practice readiness" })).toHaveText(
    "1 of 3 ready · 1 preparing · 1 needs retry",
  );
  await page.getByRole("button", { name: "Take chapter test" }).click();
  await expect(page.getByText("Thinking · 6s")).toBeVisible();

  expect(posts.practicePosts.map((post) => post.sectionId)).toEqual([]);
  expect(posts.testPosts).toEqual([
    expect.objectContaining({
      body: { chapter_label: chapterLabel },
      url: expect.stringMatching(new RegExp(`/api/courses/${courseId}/tests$`)),
    }),
  ]);
  await expectNoCriticalViolations(page, "independent-test-generation");
  await expectNoPrivateOutput(page);
  await expectCleanGuards(guards);
}

test("ready practice remains usable while sibling sections are generating", runPartialReadiness);
test("retry failed restarts only failed practice sections", runSelectiveRetry);
test("invalid model output offers retry without exposing parser details", runInvalidOutputRecovery);
test("missing Ollama model routes the student to Settings", runMissingModelRecovery);
test("chapter test generation remains available during partial practice failure", runIndependentTestGeneration);
