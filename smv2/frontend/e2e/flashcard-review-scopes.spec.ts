import { expect, test, type ConsoleMessage, type Page, type Route } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

type BrowserError =
  | { kind: "console"; type: string; text: string; location: ReturnType<ConsoleMessage["location"]> }
  | { kind: "pageerror"; message: string; stack?: string };

type ReviewScope = "available" | "all" | "needs_attention";

interface ReviewRequest {
  scope: string | null;
  chapter: string | null;
  limit: string | null;
}

interface GradeRequest {
  cardId: string;
  grade: number;
}

interface FlashcardReviewHarness {
  browserErrors: BrowserError[];
  expectedBrowserErrors: BrowserError[];
  providerCalls: string[];
  reviewRequests: ReviewRequest[];
  selectionRequests: string[][];
  graded: GradeRequest[];
  unmockedApiRequests: string[];
}

const courseId = "course-flashcard-review";
const chapterOneSectionId = "section-chapter-one";
const chapterTwoSectionId = "section-chapter-two";
const completedSessionId = "session-completed-e2e";
const now = "2026-08-09T12:00:00.000Z";
const apiProviders = [
  "**://api.anthropic.com/**",
  "**://api.openai.com/**",
  "**://127.0.0.1:11434/**",
  "**://localhost:11434/**",
];

const course = {
  id: courseId,
  title: "Unified flashcard review",
  status: "ready",
  source_type: "pdf",
  created_at: now,
  updated_at: now,
  asset_count: 1,
  failed_asset_count: 0,
};

const chapters = [
  {
    chapter_label: "Chapter 1",
    section_ids: [chapterOneSectionId],
    practice_section_ids: [],
    answers_section_ids: [],
    test_stats: null,
  },
  {
    chapter_label: "Chapter 2: Scope & Replay",
    section_ids: [chapterTwoSectionId],
    practice_section_ids: [],
    answers_section_ids: [],
    test_stats: null,
  },
];

const sections = [
  section(chapterOneSectionId, "Chapter 1", "Chapter 1"),
  section(chapterTwoSectionId, "Chapter 2: Scope & Replay", "Chapter 2: Scope & Replay"),
];

const courseCards = [
  reviewCard("card-due", chapterOneSectionId, "Chapter 1", "Define a due card.", "A due card is ready now.", {
    is_due: true,
    due_at: "2026-08-08T12:00:00.000Z",
    last_grade: 2,
    reps: 3,
  }),
  reviewCard("card-new", chapterOneSectionId, "Chapter 1", "Define a new card.", "A new card has no review state.", {
    is_new: true,
  }),
  reviewCard(
    "card-future",
    chapterTwoSectionId,
    "Chapter 2: Scope & Replay",
    "Which card proves not-due inclusion?",
    "The future-due card must still appear in all scope.",
    {
      due_at: "2026-08-15T12:00:00.000Z",
      last_grade: 1,
      interval_days: 12,
      reps: 5,
    },
  ),
  reviewCard(
    "card-missed",
    chapterTwoSectionId,
    "Chapter 2: Scope & Replay",
    "Which card should replay exactly?",
    "Only the card graded Again in the completed session.",
    {
      is_due: true,
      due_at: "2026-08-07T12:00:00.000Z",
      last_grade: 1,
    },
  ),
];

const cardOutBySection = new Map(
  sections.map((item) => [
    item.id,
    courseCards
      .filter((card) => card.section_id === item.id)
      .map((card, index) => ({
        id: card.id,
        section_id: card.section_id,
        front_md: card.front_md,
        back_md: card.back_md,
        origin: "generated",
        position: index,
        created_at: now,
      })),
  ]),
);

test.describe("unified flashcard review scopes", () => {
  test("provider guard records and blocks injected provider fetch before generic routing", async ({ page }) => {
    const harness = await installFlashcardReviewHarness(page);

    await page.goto(`/review?course=${courseId}&scope=all`);
    await expect(page.getByRole("heading", { name: "Ready to review" })).toBeVisible();

    const result = await page.evaluate(async () => {
      try {
        await fetch("https://api.openai.com/v1/chat/completions", {
          method: "POST",
          mode: "no-cors",
          body: "{}",
        });
        return "resolved";
      } catch {
        return "blocked";
      }
    });

    expect(result).toBe("blocked");
    expect(harness.providerCalls).toEqual(["POST https://api.openai.com/v1/chat/completions"]);
    expect(harness.browserErrors, "provider probe should only emit the blocked-resource browser error").toHaveLength(1);
    expect(harness.browserErrors[0]).toMatchObject({
      kind: "console",
      location: { url: "https://api.openai.com/v1/chat/completions" },
      text: expect.stringContaining("ERR_BLOCKED_BY_CLIENT"),
      type: "error",
    });
    expect(harness.unmockedApiRequests, "provider probe should not hit app API fallback").toEqual([]);
  });

  test("student reviews every card in a course including not-due cards", async ({ page }) => {
    const harness = await installFlashcardReviewHarness(page);

    await page.goto(`/review?course=${courseId}&scope=all`);
    await expect(page.getByRole("heading", { name: "Ready to review" })).toBeVisible();
    await expect(page.getByText("2 due · 1 new")).toBeVisible();
    await expectNoCriticalViolations(page, "course-all-chooser");

    const reviewAll = page.getByRole("button", { name: "Review All (4)" });
    await reviewAll.focus();
    await page.keyboard.press("Enter");

    await expect(page.getByText("Define a due card.")).toBeVisible();
    await page.keyboard.press(" ");
    await expect(page.getByText("A due card is ready now.")).toBeVisible();
    await expectNoCriticalViolations(page, "course-all-first-answer");
    await page.keyboard.press("3");

    await expect(page.getByText("Define a new card.")).toBeVisible();
    await page.keyboard.press(" ");
    await expect(page.getByText("A new card has no review state.")).toBeVisible();
    await page.keyboard.press("3");

    await expect(page.getByText("Which card proves not-due inclusion?")).toBeVisible();
    await page.keyboard.press(" ");
    await expect(page.getByText("The future-due card must still appear in all scope.")).toBeVisible();
    await expectNoCriticalViolations(page, "course-all-not-due-answer");
    await page.keyboard.press("3");

    await expect(page.getByText("Which card should replay exactly?")).toBeVisible();
    await page.keyboard.press(" ");
    await expect(page.getByText("Only the card graded Again in the completed session.")).toBeVisible();
    await page.keyboard.press("3");

    await expect(page.getByRole("heading", { name: "Session complete" })).toBeVisible();

    expect(harness.reviewRequests).toEqual([
      { scope: "all", chapter: null, limit: "200" },
      { scope: "all", chapter: null, limit: "200" },
      { scope: "all", chapter: null, limit: "4" },
    ]);
    expect(harness.graded.map((request) => request.cardId)).toEqual([
      "card-due",
      "card-new",
      "card-future",
      "card-missed",
    ]);
    await expectCleanHarness(harness);
  });

  test("student reviews needs-attention cards including a future-due Again card", async ({ page }) => {
    const harness = await installFlashcardReviewHarness(page);

    await page.goto(`/review?course=${courseId}&scope=needs_attention`);
    await expect(page.getByRole("heading", { name: "Ready to review" })).toBeVisible();
    await expect(page.getByText("1 due · 0 new")).toBeVisible();
    await expectNoCriticalViolations(page, "needs-attention-chooser");

    const reviewAll = page.getByRole("button", { name: "Review All (2)" });
    await reviewAll.focus();
    await page.keyboard.press("Enter");

    await expect(page.getByText("Which card proves not-due inclusion?")).toBeVisible();
    await page.keyboard.press(" ");
    await expect(page.getByText("The future-due card must still appear in all scope.")).toBeVisible();
    await expectNoCriticalViolations(page, "needs-attention-future-answer");
    await page.keyboard.press("4");

    await expect(page.getByText("Which card should replay exactly?")).toBeVisible();
    await page.keyboard.press(" ");
    await expect(page.getByText("Only the card graded Again in the completed session.")).toBeVisible();
    await page.keyboard.press("3");

    await expect(page.getByRole("heading", { name: "Session complete" })).toBeVisible();

    expect(harness.reviewRequests).toEqual([
      { scope: "needs_attention", chapter: null, limit: "200" },
      { scope: "needs_attention", chapter: null, limit: "200" },
      { scope: "needs_attention", chapter: null, limit: "2" },
    ]);
    expect(harness.graded).toEqual([
      { cardId: "card-future", grade: 4 },
      { cardId: "card-missed", grade: 3 },
    ]);
    await expectCleanHarness(harness);
  });

  test("student reviews only one chapter from the flashcards library", async ({ page }) => {
    const harness = await installFlashcardReviewHarness(page);

    await page.goto("/flashcards");
    await expect(page.getByRole("heading", { name: "Flashcards" })).toBeVisible();
    await page.getByRole("button", { name: "Browse" }).nth(1).focus();
    await page.keyboard.press("Enter");

    const reviewChapter = page.getByRole("link", { name: "Review chapter" }).nth(1);
    await expect(reviewChapter).toHaveAttribute(
      "href",
      `/review?course=${courseId}&scope=all&chapter=Chapter%202%3A%20Scope%20%26%20Replay`,
    );
    await expectNoCriticalViolations(page, "chapter-library");
    await reviewChapter.focus();
    await page.keyboard.press("Enter");

    await expect(page).toHaveURL(/scope=all/);
    await expect(page).toHaveURL(/chapter=Chapter%202%3A%20Scope%20%26%20Replay/);
    await expect(page.getByRole("heading", { name: "Ready to review" })).toBeVisible();
    const reviewAll = page.getByRole("button", { name: "Review All (2)" });
    await reviewAll.focus();
    await page.keyboard.press("Enter");

    await expect(page.getByText("Which card proves not-due inclusion?")).toBeVisible();
    await page.keyboard.press(" ");
    await expect(page.getByText("The future-due card must still appear in all scope.")).toBeVisible();
    await expectNoCriticalViolations(page, "chapter-review-first-answer");
    await page.keyboard.press("3");

    await expect(page.getByText("Which card should replay exactly?")).toBeVisible();
    await expect(page.getByText("Define a due card.")).not.toBeVisible();
    await expect(page.getByText("Define a new card.")).not.toBeVisible();
    await page.keyboard.press(" ");
    await expect(page.getByText("Only the card graded Again in the completed session.")).toBeVisible();
    await expectNoCriticalViolations(page, "chapter-review-second-answer");
    await page.keyboard.press("2");

    await expect(page.getByRole("heading", { name: "Session complete" })).toBeVisible();

    expect(harness.reviewRequests).toEqual([
      { scope: "all", chapter: "Chapter 2: Scope & Replay", limit: "200" },
      { scope: "all", chapter: "Chapter 2: Scope & Replay", limit: "200" },
      { scope: "all", chapter: "Chapter 2: Scope & Replay", limit: "2" },
    ]);
    expect(harness.graded).toEqual([
      { cardId: "card-future", grade: 3 },
      { cardId: "card-missed", grade: 2 },
    ]);
    await expectCleanHarness(harness);
  });

  test("student grades a revealed card inside the chapter reader", async ({ page }) => {
    const harness = await installFlashcardReviewHarness(page);

    await page.addInitScript(() => window.localStorage.setItem("smv2.reader.view", "source"));
    await page.goto(`/course/${courseId}?section=${chapterTwoSectionId}`);
    await expect(page.getByRole("heading", { name: "Chapter 2: Scope & Replay", exact: true })).toBeVisible();

    const showAnswer = page.getByRole("button", { name: "Show answer" }).first();
    await showAnswer.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("The future-due card must still appear in all scope.")).toBeVisible();
    await expectNoCriticalViolations(page, "inline-reader-revealed");

    const hard = page.getByRole("button", { name: /Hard \(2\)/ }).first();
    await hard.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Saved as Hard.")).toBeVisible();
    await expectNoCriticalViolations(page, "inline-reader-saved-grade");

    expect(harness.reviewRequests).toEqual([
      { scope: "all", chapter: "Chapter 2: Scope & Replay", limit: "200" },
      { scope: "all", chapter: "Chapter 2: Scope & Replay", limit: "200" },
    ]);
    expect(harness.graded).toEqual([{ cardId: "card-future", grade: 2 }]);
    await expectCleanHarness(harness);
  });

  test("completed review returns to chooser and replays exact missed cards", async ({ page }) => {
    const harness = await installFlashcardReviewHarness(page);
    await seedCompletedSession(page, ["card-missed", "card-future"]);

    await page.goto(`/review?course=${courseId}&completed=${completedSessionId}`);
    await expect(page.getByRole("heading", { name: "Session complete" })).toBeVisible();
    await expectNoCriticalViolations(page, "completed-session");

    const backToReview = page.getByRole("button", { name: "Back to review" });
    await backToReview.focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(`/review?course=${courseId}`);
    await expect(page.getByRole("heading", { name: "Ready to review" })).toBeVisible();
    await expectNoCriticalViolations(page, "completed-back-to-review-chooser");

    await page.goto(`/review?course=${courseId}&completed=${completedSessionId}`);
    const missed = page.getByRole("button", { name: "Review missed (2)" });
    await missed.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Which card should replay exactly?")).toBeVisible();
    await expect(page.getByText("Define a due card.")).not.toBeVisible();
    await expect(page.getByText("Define a new card.")).not.toBeVisible();
    await page.keyboard.press(" ");
    await expect(page.getByText("Only the card graded Again in the completed session.")).toBeVisible();
    await expectNoCriticalViolations(page, "missed-replay-first-answer");
    await page.keyboard.press("3");

    await expect(page.getByText("Which card proves not-due inclusion?")).toBeVisible();
    await page.keyboard.press(" ");
    await expect(page.getByText("The future-due card must still appear in all scope.")).toBeVisible();
    await expectNoCriticalViolations(page, "missed-replay-second-answer");
    await page.keyboard.press("4");

    await expect(page.getByRole("heading", { name: "Session complete" })).toBeVisible();

    expect(harness.selectionRequests).toEqual([["card-missed", "card-future"]]);
    expect(harness.graded).toEqual([
      { cardId: "card-missed", grade: 3 },
      { cardId: "card-future", grade: 4 },
    ]);
    await expectCleanHarness(harness);
  });

  test("failed grade remains on the same card with retry guidance", async ({ page }) => {
    const harness = await installFlashcardReviewHarness(page, { failNextGrade: true });

    await page.goto(`/review?course=${courseId}&scope=all`);
    await expect(page.getByRole("heading", { name: "Ready to review" })).toBeVisible();
    const reviewAll = page.getByRole("button", { name: "Review All (4)" });
    await reviewAll.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Define a due card.")).toBeVisible();
    await page.keyboard.press(" ");
    await expectNoCriticalViolations(page, "failed-grade-revealed");

    await page.keyboard.press("1");
    await expect(page.getByText("Could not save this grade. Try again.")).toBeVisible();
    await expect(page.getByText("Define a due card.")).toBeVisible();
    await expect(page.getByText("A due card is ready now.")).toBeVisible();
    await expectNoCriticalViolations(page, "failed-grade-retry-guidance");

    await page.keyboard.press("1");
    await expect(page.getByText("Define a new card.")).toBeVisible();
    expect(harness.graded).toEqual([
      { cardId: "card-due", grade: 1 },
      { cardId: "card-due", grade: 1 },
    ]);
    expect(harness.expectedBrowserErrors).toHaveLength(1);
    await expectCleanHarness(harness);
  });
});

async function installFlashcardReviewHarness(
  page: Page,
  options: { failNextGrade?: boolean } = {},
): Promise<FlashcardReviewHarness> {
  const expectedBrowserErrors: BrowserError[] = [];
  const browserErrors = attachBrowserErrorGuard(page, (error) => {
    if (!options.failNextGrade || error.kind !== "console") return false;
    return (
      error.location.url === `http://127.0.0.1:8000/api/cards/card-due/grade` &&
      error.text === "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
    );
  }, expectedBrowserErrors);
  const providerCalls: string[] = [];
  const unmockedApiRequests: string[] = [];
  const reviewRequests: ReviewRequest[] = [];
  const selectionRequests: string[][] = [];
  const graded: GradeRequest[] = [];
  let failNextGrade = options.failNextGrade === true;

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (isProviderUrl(url)) {
      providerCalls.push(`${request.method()} ${request.url()}`);
      await route.abort("blockedbyclient");
      return;
    }
    if (!url.pathname.startsWith("/api") && url.pathname !== "/health") {
      await route.continue();
      return;
    }

    if (url.pathname === "/health") return fulfillJson(route, { ok: true });
    if (url.pathname === "/api/settings") return fulfillJson(route, mockedSettings());
    if (url.pathname === "/api/settings/bootstrap") {
      return fulfillJson(route, { csrf_token: "csrf-e2e", rollout: { local_settings_enabled: true } });
    }
    if (url.pathname === "/api/courses") return fulfillJson(route, [course]);
    if (url.pathname === `/api/courses/${courseId}`) return fulfillJson(route, course);
    if (url.pathname === `/api/courses/${courseId}/chapters`) return fulfillJson(route, chapters);
    if (url.pathname === `/api/courses/${courseId}/sections`) return fulfillJson(route, sections);
    if (url.pathname === `/api/courses/${courseId}/progress`) {
      return fulfillJson(route, {
        course_id: courseId,
        section_id: chapterOneSectionId,
        scroll_pos: 0,
        updated_at: now,
      });
    }
    if (url.pathname === `/api/courses/${courseId}/highlights`) return fulfillJson(route, []);
    if (url.pathname === `/api/courses/${courseId}/notes`) return fulfillJson(route, []);
    if (url.pathname === "/api/llm/usage" || url.pathname === `/api/courses/${courseId}/llm/usage`) {
      return fulfillJson(route, { calls: 0, input_tokens: 0, output_tokens: 0, est_cost_usd: 0 });
    }
    if (url.pathname === "/api/jobs") return fulfillJson(route, []);
    if (url.pathname === "/api/review/summary") {
      return fulfillJson(route, {
        due_total: 2,
        daily_throughput: 20,
        backlog_warning: false,
        courses: [
          {
            course_id: courseId,
            title: course.title,
            due_count: 2,
            overdue_count: 2,
            new_count: 1,
            available_count: 3,
            total_count: 4,
            needs_attention_count: 2,
          },
        ],
      });
    }
    if (url.pathname === `/api/courses/${courseId}/study/queue`) {
      return fulfillJson(route, { activities: [] });
    }
    if (url.pathname === `/api/courses/${courseId}/review/queue`) {
      reviewRequests.push({
        scope: url.searchParams.get("scope"),
        chapter: url.searchParams.get("chapter_label"),
        limit: url.searchParams.get("limit"),
      });
      const scope = (url.searchParams.get("scope") ?? "available") as ReviewScope;
      const chapter = url.searchParams.get("chapter_label");
      const limit = Number(url.searchParams.get("limit") ?? courseCards.length);
      const cards = filteredReviewCards(scope, chapter).slice(0, limit);
      return fulfillJson(route, reviewQueue(cards));
    }
    if (url.pathname === `/api/courses/${courseId}/review/selection`) {
      const body = request.postDataJSON() as { card_ids?: string[] };
      const requested = body.card_ids ?? [];
      selectionRequests.push(requested);
      const byId = new Map(courseCards.map((card) => [card.id, card]));
      return fulfillJson(route, {
        cards: requested.map((id) => byId.get(id)).filter(Boolean),
        missing_card_ids: requested.filter((id) => !byId.has(id)),
      });
    }

    const sectionMatch = url.pathname.match(/^\/api\/sections\/([^/]+)$/);
    if (sectionMatch) {
      const sectionRow = sections.find((item) => item.id === sectionMatch[1]);
      if (sectionRow) return fulfillJson(route, { ...sectionRow, body_md: `# ${sectionRow.title}\n\nReader body.` });
    }

    const cardsMatch = url.pathname.match(/^\/api\/sections\/([^/]+)\/cards$/);
    if (cardsMatch) return fulfillJson(route, cardOutBySection.get(cardsMatch[1]) ?? []);

    const gradeMatch = url.pathname.match(/^\/api\/cards\/([^/]+)\/grade$/);
    if (gradeMatch) {
      const body = request.postDataJSON() as { grade?: number; elapsed_ms?: number };
      graded.push({ cardId: gradeMatch[1], grade: body.grade ?? 0 });
      if (failNextGrade) {
        failNextGrade = false;
        return fulfillJson(route, { detail: "temporary grade failure" }, 503);
      }
      return fulfillJson(route, {
        card_id: gradeMatch[1],
        grade: body.grade,
        due_at: "2026-08-10T12:00:00.000Z",
        interval_days: 1,
        ease: 2.5,
        reps: 1,
      });
    }

    unmockedApiRequests.push(`${request.method()} ${url.pathname}${url.search}`);
    return fulfillJson(route, { detail: "unmocked e2e API request" }, 500);
  });

  return {
    browserErrors,
    expectedBrowserErrors,
    providerCalls,
    reviewRequests,
    selectionRequests,
    graded,
    unmockedApiRequests,
  };
}

function attachBrowserErrorGuard(
  page: Page,
  isExpectedError: (error: BrowserError) => boolean = () => false,
  expectedErrors: BrowserError[] = [],
): BrowserError[] {
  const errors: BrowserError[] = [];
  page.on("pageerror", (error) => {
    const browserError = { kind: "pageerror" as const, message: error.message, stack: error.stack };
    if (isExpectedError(browserError)) expectedErrors.push(browserError);
    else errors.push(browserError);
  });
  page.on("console", (message) => {
    if (message.type() === "error") {
      const browserError = {
        kind: "console",
        type: message.type(),
        text: message.text(),
        location: message.location(),
      } as const;
      if (isExpectedError(browserError)) expectedErrors.push(browserError);
      else errors.push(browserError);
    }
  });
  return errors;
}

function isProviderUrl(url: URL): boolean {
  return apiProviders.some((pattern) => {
    if (pattern.includes("api.anthropic.com")) return url.hostname === "api.anthropic.com";
    if (pattern.includes("api.openai.com")) return url.hostname === "api.openai.com";
    if (pattern.includes("127.0.0.1:11434")) return url.hostname === "127.0.0.1" && url.port === "11434";
    if (pattern.includes("localhost:11434")) return url.hostname === "localhost" && url.port === "11434";
    return false;
  });
}

async function expectNoCriticalViolations(page: Page, name: string) {
  const results = await new AxeBuilder({ page }).include("body").analyze();
  const critical = results.violations.filter((violation) => violation.impact === "critical");
  test.info().annotations.push({
    type: `axe:${name}`,
    description: critical.map((violation) => `${violation.id}:${violation.nodes.length}`).join(", ") || "none",
  });
  expect(critical).toEqual([]);
}

async function expectCleanHarness(harness: FlashcardReviewHarness) {
  expect(harness.browserErrors, "no uncaught page errors or console errors").toEqual([]);
  expect(harness.providerCalls, "no paid-provider or Ollama calls").toEqual([]);
  expect(harness.unmockedApiRequests, "all API calls are route-intercepted").toEqual([]);
}

async function seedCompletedSession(page: Page, againCardIds: string[]) {
  await page.addInitScript(
    ({ courseId, sessionId, againCardIds }) => {
      window.localStorage.setItem(
        "smv2.review.completedSession",
        JSON.stringify({
          version: 1,
          sessionId,
          courseId,
          scope: "all",
          chapterLabel: "Chapter 2: Scope & Replay",
          endedAt: Date.now(),
          gradedTally: { 1: againCardIds.length, 2: 0, 3: 1, 4: 0 },
          againCardIds,
        }),
      );
    },
    { courseId, sessionId: completedSessionId, againCardIds },
  );
}

function section(id: string, title: string, chapterLabel: string) {
  return {
    id,
    title,
    course_id: courseId,
    order_index: id === chapterOneSectionId ? 1 : 2,
    page_start: 1,
    page_end: 2,
    kind: "content",
    chapter_label: chapterLabel,
    asset_id: null,
    has_content: true,
    word_count: 120,
    lesson_status: "none",
    source_format: "markdown",
    source_locator: null,
  };
}

function reviewCard(
  id: string,
  sectionId: string,
  chapterLabel: string,
  frontMd: string,
  backMd: string,
  overrides: Partial<{
    due_at: string | null;
    ease: number;
    interval_days: number;
    is_due: boolean;
    is_new: boolean;
    last_grade: number | null;
    reps: number;
  }> = {},
) {
  return {
    id,
    section_id: sectionId,
    section_title: chapterLabel,
    chapter_label: chapterLabel,
    front_md: frontMd,
    back_md: backMd,
    due_at: overrides.due_at ?? null,
    ease: overrides.ease ?? 2.5,
    interval_days: overrides.interval_days ?? 0,
    is_due: overrides.is_due ?? false,
    is_new: overrides.is_new ?? false,
    last_grade: overrides.last_grade ?? null,
    reps: overrides.reps ?? 0,
  };
}

function filteredReviewCards(scope: ReviewScope, chapter: string | null) {
  const scoped = courseCards.filter((card) => {
    if (scope === "needs_attention") return card.last_grade === 1;
    if (scope === "available") return card.is_due || card.is_new;
    return true;
  });
  return chapter ? scoped.filter((card) => card.chapter_label === chapter) : scoped;
}

function reviewQueue(cards: typeof courseCards) {
  return {
    cards,
    due: cards.filter((card) => card.is_due).length,
    new: cards.filter((card) => card.is_new).length,
    total: cards.length,
    overdue_count: cards.filter((card) => card.is_due).length,
    new_count: cards.filter((card) => card.is_new).length,
    available_count: cards.filter((card) => card.is_due || card.is_new).length,
    total_count: cards.length,
  };
}

function mockedSettings() {
  return {
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
  };
}

async function fulfillJson(route: Route, json: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(json),
  });
}
